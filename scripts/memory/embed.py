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
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32)


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
