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
    """Convert text to a 512-dim L2-normalized float32 embedding vector.

    Args:
        text: Input string to embed.

    Returns:
        numpy.ndarray of shape (512,), dtype float32, L2-normalized.
    """
    model = _get_model()
    try:
        vec = model.encode(text, normalize_embeddings=True)
        return vec.astype(np.float32)
    except Exception as e:
        import sys
        print(f'⚠️ 向量编码失败: {e}', file=sys.stderr)
        return np.zeros(512, dtype=np.float32)


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

import faiss as _faiss

FAISS_INDEX_FILE = "vector.faiss"


def _get_faiss_path():
    """Absolute path to the FAISS index file."""
    return os.path.join(MODELS_DIR, "..", FAISS_INDEX_FILE)


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

    index = _faiss.IndexIDMap(_faiss.IndexFlatIP(vectors.shape[1]))
    index.add_with_ids(vectors, seqs)

    path = _get_faiss_path()
    _faiss.write_index(index, path)
    return index


def load_faiss_index():
    """Load a previously persisted FAISS index, or None."""
    path = _get_faiss_path()
    if not os.path.exists(path):
        return None
    return _faiss.read_index(path)


def vector_search(query, db, limit=10):
    """Primary vector-first semantic search.

    Uses the persisted FAISS index when available; falls back to an
    in-memory brute-force cosine scan if no index exists yet.
    Returns a list of (score, seq, type, content, topics).
    """
    index = load_faiss_index()
    if index is None:
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
