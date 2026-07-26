"""Text embedding via sentence-transformers (optional dependency).

Provides semantic vector search for the memory system.
Requires: pip install sentence-transformers

Usage:
    import embed
    embed.download_model()        # one-time setup
    vec = embed.embed("text")     # shape=(512,), dtype=float32, L2-normalized
    embed.search(query, entries)  # cosine similarity search
"""

import os
import sys
import time
import numpy as np

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODELS_DIR = os.path.join(os.path.expanduser("~/.codex/memory"), "models")

_model = None


def is_available():
    """Return True if sentence-transformers is installed and usable."""
    try:
        import sentence_transformers
        return True
    except ImportError:
        return False


def _get_model():
    """Lazy-load the SentenceTransformer model (cached after first call)."""
    global _model
    # Force offline mode to prevent network access attempts in sandbox
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    if _model is None:
        from sentence_transformers import SentenceTransformer
        if not os.path.exists(MODELS_DIR) or not os.listdir(MODELS_DIR):
            download_model()
        _model = SentenceTransformer(MODELS_DIR)
    return _model


def download_model():
    """Download model files to MODELS_DIR via HuggingFace Hub."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=MODEL_NAME,
        local_dir=MODELS_DIR,
        local_dir_use_symlinks=False,
    )
    print(f"模型已就绪: {MODEL_NAME}")


def embed(text):
    """Convert text to a 512-dim L2-normalized float32 embedding vector with retry.

    Args:
        text: Input string to embed.

    Returns:
        numpy.ndarray of shape (512,), dtype float32, L2-normalized.
        Returns zero vector if all retries fail.
    """
    model = _get_model()
    last_exc = None
    for attempt in range(3):
        try:
            vec = model.encode(text, normalize_embeddings=True)
            result = vec.astype(np.float32)
            if result.any():
                return result
            if attempt < 2:
                time.sleep(1.0 * (2 ** attempt))
                continue
        except Exception as e:
            last_exc = e
            if attempt < 2:
                time.sleep(1.0 * (2 ** attempt))
                continue
    import sys
    print(f"⚠️ 向量编码失败 (3 次重试): {last_exc}", file=sys.stderr)
    return np.zeros(512, dtype=np.float32)


def embed_batch(texts, batch_size=32):
    """Embed multiple texts in batch for better throughput.

    Falls back to single-item embed() for any zero-vector result,
    and for the entire batch if batch encoding fails completely.

    Args:
        texts: List of strings to embed.
        batch_size: Batch size for model.encode(). Default 32.

    Returns:
        List[np.ndarray] of shape-(512,) float32 vectors, same order as input.
    """
    model = _get_model()
    try:
        vectors = model.encode(texts, batch_size=batch_size,
                                normalize_embeddings=True, show_progress_bar=False)
        vectors = vectors.astype(np.float32)
    except Exception as e:
        import sys
        print(f"⚠️ 批量编码失败 ({len(texts)} 条): {e}，降级逐条编码", file=sys.stderr)
        return [embed(t) for t in texts]

    results = []
    for i, vec in enumerate(vectors):
        if not vec.any():
            import sys
            print(f"⚠️ 第 {i} 条批量嵌入为零向量，单条重试", file=sys.stderr)
            results.append(embed(texts[i]))
        else:
            results.append(vec)
    return results


def cosine_similarity(a, b):
    """Cosine similarity between two float32 vectors."""
    dot = float(np.dot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return dot / (norm + 1e-12)


def search(query, entries, limit=5):
    """Rank entries by cosine similarity to query.

    Args:
        query: Search string.
        entries: List of (seq, vector_bytes) tuples.
        limit: Max results.

    Returns:
        List of (score, seq) sorted by descending score.
    """
    if not entries:
        return []
    q_vec = embed(query)
    scored = []
    for seq, vec_bytes in entries:
        try:
            vec = np.frombuffer(bytes(vec_bytes), dtype=np.float32)
            score = cosine_similarity(q_vec, vec)
            scored.append((score, seq))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[0])
    return scored[:limit]


# ---- FAISS vector index -----------------------------------------------


FAISS_INDEX_FILE = "vector.faiss"

# Override point: main.py sets this to the active MEMORY_DIR so the
# FAISS index lives alongside memory.db.  Tests automatically get
# isolated index files without any special mocking.
_faiss_dir = None


def set_faiss_dir(path):
    """Point the FAISS index at a specific directory (e.g. MEMORY_DIR)."""
    global _faiss_dir
    _faiss_dir = path


def _get_faiss():
    """Lazy-import faiss so embed.py works without faiss-cpu installed."""
    import faiss
    return faiss


def _get_faiss_path():
    """Absolute path to the FAISS index file."""
    base = _faiss_dir if _faiss_dir else os.path.join(MODELS_DIR, "..")
    return os.path.join(base, FAISS_INDEX_FILE)


def build_faiss_index(db):
    """Build a FAISS IndexIDMap from all entries in entries_vec and persist it.

    Uses IndexFlatIP (inner product) which is equivalent to cosine
    similarity when vectors are L2-normalized.
    """
    rows = db.execute(
        "SELECT seq, vector FROM entries_vec ORDER BY seq"
    ).fetchall()
    if not rows:
        return None

    vectors = np.zeros((len(rows), 512), dtype=np.float32)
    seqs    = np.zeros(len(rows), dtype=np.int64)
    for i, row in enumerate(rows):
        vectors[i] = np.frombuffer(bytes(row["vector"]), dtype=np.float32)
        seqs[i]    = row["seq"]

    index = _get_faiss().IndexIDMap(_get_faiss().IndexFlatIP(vectors.shape[1]))
    index.add_with_ids(vectors, seqs)

    path = _get_faiss_path()
    _get_faiss().write_index(index, path)
    return index


def load_faiss_index():
    """Load a previously persisted FAISS index, or None."""
    path = _get_faiss_path()
    if not os.path.exists(path):
        return None
    return _get_faiss().read_index(path)


def vector_search(query, db, limit=10):
    """Primary vector-first semantic search.

    Uses the persisted FAISS index when available; falls back to an
    in-memory brute-force cosine scan if no index exists yet.
    Returns a list of (score, seq, type, content, topics).

    When neither a FAISS index nor any entries_vec rows exist,
    returns an empty list immediately to avoid unnecessary model
    loading (important for tests)."""
    index = load_faiss_index()
    if index is None:
        # Quick guard: don't load the embedding model if there's
        # nothing to compare against.
        count = db.execute(
            "SELECT count(*) FROM entries_vec"
        ).fetchone()[0]
        if count == 0:
            return []
        return _brute_force_search(query, db, limit)

    q_vec = embed(query).reshape(1, -1).astype(np.float32)
    scores, indices = index.search(q_vec, min(limit, index.ntotal))

    results = []
    for idx, score in zip(indices[0], scores[0]):
        if idx < 0:
            continue
        seq = int(idx)
        row = db.execute(
            "SELECT e.seq, e.type, e.content, e.topics FROM entries e "
            "WHERE e.seq = ? AND e.deleted = 0", (seq,)
        ).fetchone()
        if row:
            results.append((float(score), row["seq"], row["type"],
                            row["content"], row["topics"]))
    return results


def _brute_force_search(query, db, limit=10):
    """Fallback: scan all vectors and compute cosine similarity."""
    vec_entries = db.execute(
        "SELECT e.seq, v.vector FROM entries_vec v "
        "JOIN entries e ON v.seq = e.seq WHERE e.deleted=0"
    ).fetchall()
    if not vec_entries:
        return []

    q_vec = embed(query)
    scored = []
    for seq, vec_bytes in vec_entries:
        try:
            vec = np.frombuffer(bytes(vec_bytes), dtype=np.float32)
            score = cosine_similarity(q_vec, vec)
            scored.append((score, seq))
        except Exception:
            continue
    scored.sort(key=lambda x: -x[0])

    results = []
    for score, seq in scored[:limit]:
        row = db.execute(
            "SELECT e.seq, e.type, e.content, e.topics FROM entries e "
            "WHERE e.seq = ? AND e.deleted = 0", (seq,)
        ).fetchone()
        if row:
            results.append((score, row["seq"], row["type"],
                            row["content"], row["topics"]))
    return results


def delete_faiss_index():
    """Remove the persisted FAISS index so it can be rebuilt."""
    path = _get_faiss_path()
    if os.path.exists(path):
        os.remove(path)
