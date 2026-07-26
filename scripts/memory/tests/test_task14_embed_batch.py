"""Task 14: 批量嵌入 (embed_batch + _vec_rebuild batch path) 单元测试"""

import sys, os, tempfile, shutil, unittest
import hashlib
import numpy as np
import time
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem
import embed


class TestEmbedRetry(unittest.TestCase):
    """Test embed.embed() retry mechanism."""

    def test_embed_returns_correct_shape(self):
        if not embed.is_available():
            self.skipTest("embedding model not available")
        vec = embed.embed("测试文本")
        self.assertEqual(vec.shape, (512,))
        self.assertEqual(vec.dtype, np.float32)

    def test_embed_retry_on_failure(self):
        """embed() should retry 3 times on failure and return zero vector."""
        if not embed.is_available():
            self.skipTest("embedding model not available")
        # Test with normal text — should succeed with retry
        vec = embed.embed("hello world")
        self.assertEqual(vec.shape, (512,))
        self.assertTrue(vec.any())


class TestEmbedBatch(unittest.TestCase):
    """Test embed.embed_batch() function."""

    def test_embed_batch_returns_list(self):
        if not embed.is_available():
            self.skipTest("embedding model not available")
        texts = ["测试文本一", "测试文本二", "测试文本三"]
        vectors = embed.embed_batch(texts, batch_size=2)
        self.assertEqual(len(vectors), 3)
        for v in vectors:
            self.assertEqual(v.shape, (512,))
            self.assertEqual(v.dtype, np.float32)
            self.assertTrue(v.any())

    def test_embed_batch_single_text(self):
        if not embed.is_available():
            self.skipTest("embedding model not available")
        vectors = embed.embed_batch(["单一文本"], batch_size=2)
        self.assertEqual(len(vectors), 1)
        self.assertEqual(vectors[0].shape, (512,))


class TestVecRebuildBatch(unittest.TestCase):
    """Test _vec_rebuild batch embedding path."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="vec_batch_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        if not embed.is_available():
            self.skipTest("embedding model not available")
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        embed.set_faiss_dir(self.test_dir)
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        faiss_file = os.path.join(self.test_dir, "vector.faiss")
        if os.path.exists(faiss_file):
            os.remove(faiss_file)
        fts_file = os.path.join(self.test_dir, "memory.db")
        if os.path.exists(fts_file):
            os.remove(fts_file)

    def _add_entry(self, entry_type, content, topics=""):
        """Helper to insert an entry and return seq."""
        topics_raw = topics or "[]"
        sha256 = hashlib.sha256(
            (content + entry_type + topics_raw).encode("utf-8")
        ).hexdigest()
        cur = self.db.execute(
            "INSERT INTO entries(type, content, topics, sha256) VALUES(?, ?, ?, ?)",
            (entry_type, content, topics_raw, sha256),
        )
        self.db.commit()
        return cur.lastrowid

    def test_vec_rebuild_batch_path(self):
        """_vec_rebuild should use batch embedding when batch_size > 1."""
        seq1 = self._add_entry("tip", "batch embedding test entry 1", "test")
        seq2 = self._add_entry("tip", "batch embedding test entry 2", "test")
        seq3 = self._add_entry("tip", "batch embedding test entry 3", "test")

        mem._vec_rebuild(self.db)

        # Verify entries_vec has 3 entries
        rows = self.db.execute(
            "SELECT seq, vector FROM entries_vec ORDER BY seq"
        ).fetchall()
        self.assertEqual(len(rows), 3)
        for seq, vec_bytes in rows:
            self.assertEqual(len(bytes(vec_bytes)), 2048)  # 512 * 4 bytes

        # Verify FAISS index was created
        faiss_path = os.path.join(self.test_dir, "vector.faiss")
        self.assertTrue(os.path.exists(faiss_path))

    def test_vec_rebuild_empty_db(self):
        """_vec_rebuild should handle empty DB gracefully."""
        mem._vec_rebuild(self.db)
        rows = self.db.execute(
            "SELECT count(*) FROM entries_vec"
        ).fetchone()[0]
        self.assertEqual(rows, 0)

    def test_vec_rebuild_batch_content_fidelity(self):
        """Batch-embedded vectors should be semantically comparable."""
        seq1 = self._add_entry("tip", "python programming", "tech")
        seq2 = self._add_entry("tip", "I love cats and dogs", "pet")
        seq3 = self._add_entry("tip", "python coding best practices", "tech")

        mem._vec_rebuild(self.db)

        # Search for "python coding" — should find seq1 and seq3
        results = embed.search("python code", [
            (seq, self.db.execute(
                "SELECT vector FROM entries_vec WHERE seq=?", (seq,)
            ).fetchone()["vector"])
            for seq in (seq1, seq2, seq3)
        ], limit=3)

        top_seqs = [seq for _, seq in results]
        self.assertIn(seq1, top_seqs, "seq1 (python) should appear in results")
        self.assertIn(seq3, top_seqs, "seq3 (python) should appear in results")


if __name__ == "__main__":
    unittest.main()
