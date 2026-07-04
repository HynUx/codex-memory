"""Task 5: memory evolve 单元测试"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestEvolve(unittest.TestCase):
    """Test the evolve command."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="evolve_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        # Remove any leftover project-context.md from previous test
        pc = os.path.join(self.test_dir, "project-context.md")
        if os.path.exists(pc):
            os.remove(pc)
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        pc = os.path.join(self.test_dir, "project-context.md")
        if os.path.exists(pc):
            os.remove(pc)
        # cleanup temp files
        tmp = pc + ".tmp"
        if os.path.exists(tmp):
            os.remove(tmp)

    def _add(self, content, type="workflow", topics="[]"):
        args = Namespace(type=type, content=content, topics=topics, no_evolve=True)
        mem.cmd_add(args)

    def _evolve(self):
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            rc = mem.cmd_evolve(Namespace())
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        return rc, out

    def test_evolve_empty(self):
        """No unmerged entries → no change."""
        rc, out = self._evolve()
        self.assertEqual(rc, 0)
        self.assertIn("没有", out)

    def test_evolve_basic(self):
        """Add entry → evolve → project-context.md created."""
        self._add("evolve test content")
        rc, out = self._evolve()
        self.assertEqual(rc, 0)
        self.assertIn("进化完成", out)
        pc = os.path.join(self.test_dir, "project-context.md")
        self.assertTrue(os.path.exists(pc))
        with open(pc) as f:
            text = f.read()
        self.assertIn("evolve test content", text)
        self.assertIn("<!-- evolve_seq:", text)

    def test_evolve_updates_seq(self):
        """After evolve, entries should have consolidated_seq set."""
        self._add("seq test")
        seq = self.db.execute("SELECT seq FROM entries WHERE content='seq test'").fetchone()["seq"]
        self._evolve()
        row = self.db.execute(
            "SELECT consolidated_seq FROM entries WHERE seq=?", (seq,)
        ).fetchone()
        self.assertIsNotNone(row["consolidated_seq"])
        self.assertGreater(row["consolidated_seq"], 0)

    def test_evolve_increments_evolves(self):
        """evolve should increment system.total_evolves."""
        self._add("count evolve")
        self._evolve()
        te = self.db.execute("SELECT value FROM system WHERE key='total_evolves'").fetchone()["value"]
        self.assertGreaterEqual(int(te), 1)

    def test_evolve_skips_consolidated(self):
        """Already consolidated entries should not be re-processed."""
        self._add("skip me")
        self._evolve()
        # Second evolve should find nothing new
        rc, out = self._evolve()
        self.assertIn("没有", out)

    def test_evolve_backup_created(self):
        """Second evolve should create backup of first project-context.md."""
        self._add("backup test")
        backup_dir = os.path.join(self.test_dir, ".backup")
        self.assertFalse(os.path.exists(backup_dir))
        self._evolve()
        self.assertTrue(os.path.exists(backup_dir))
        # First evolve: no prior file to back up, so backup dir is empty
        self.assertEqual(len(os.listdir(backup_dir)), 0)
        self._add("second entry")
        self._evolve()
        # Second evolve: first project-context.md was backed up
        self.assertGreater(len(os.listdir(backup_dir)), 0)


if __name__ == "__main__":
    unittest.main()
