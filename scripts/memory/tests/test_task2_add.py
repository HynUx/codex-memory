"""Task 2: memory add command 单元测试"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestAddCommand(unittest.TestCase):
    """Test the `memory add` command."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="add_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _add(self, type="workflow", content="test entry", topics="[]",
             no_evolve=True):
        args = Namespace(type=type, content=content, topics=topics, no_evolve=no_evolve)
        from io import StringIO
        old_out = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_add(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old_out

    def test_add_success(self):
        rc, out = self._add()
        self.assertIsNone(rc)
        self.assertIn("✓", out)
        row = self.db.execute("SELECT seq,type,content,topics FROM entries WHERE deleted=0").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["content"], "test entry")

    def test_add_dedup(self):
        self._add(content="dedup test")
        rc, out = self._add(content="dedup test")
        self.assertIsNone(rc)
        self.assertIn("⏭", out)
        self.assertEqual(self.db.execute("SELECT count(*) FROM entries WHERE deleted=0").fetchone()[0], 1)

    def test_add_invalid_type(self):
        rc, out = self._add(type="invalid")
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_empty_content(self):
        rc, out = self._add(content="")
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_blank_content(self):
        rc, out = self._add(content="   ")
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_with_topics(self):
        rc, _ = self._add(content="topic test", topics='["codex","memory"]')
        self.assertIsNone(rc)
        row = self.db.execute("SELECT topics FROM entries WHERE content='topic test'").fetchone()
        self.assertIn("codex", row["topics"])

    def test_add_seq_increment(self):
        for i in range(3):
            rc, _ = self._add(content=f"seq test {i}")
            self.assertIsNone(rc)
        seqs = [r["seq"] for r in self.db.execute(
            "SELECT seq FROM entries WHERE deleted=0 ORDER BY seq").fetchall()]
        self.assertEqual(seqs, [1, 2, 3])

    def test_add_triggers_total_adds(self):
        self._add(content="count test")
        total = self.db.execute(
            "SELECT value FROM system WHERE key='total_adds'"
        ).fetchone()
        self.assertIsNotNone(total)
        self.assertGreaterEqual(int(total["value"]), 1)

    def test_add_fts_sync(self):
        self._add(content="fts sync test abc123")
        hit = self.db.execute(
            "SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'abc123'"
        ).fetchone()
        self.assertIsNotNone(hit)


if __name__ == "__main__":
    unittest.main()
