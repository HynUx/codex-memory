"""Task 11: Integration test — full add→evolve→load→search chain.

Covers:
  - Add → Evolve → Load → Search full-chain workflow
  - Correction loop: add → evolve → delete/update → evolve → verify
  - Consecutive evolves with new unmerged data
  - Auto-evolve trigger from cmd_add
  - FTS5 search still works after evolve
  - project-context.md format and evolve_seq tracking
"""

import sys, os, tempfile, shutil, unittest, json
from argparse import Namespace
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestIntegration(unittest.TestCase):
    """Full-chain integration tests for memory system."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="integration_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        for fname in ["profile.md", "project-context.md"]:
            fp = os.path.join(self.test_dir, fname)
            if os.path.exists(fp):
                os.remove(fp)
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def tearDown(self):
        if mem._lock_fd is not None:
            mem.release_lock()
        for fname in ["memory.db", "project-context.md", "config.toml"]:
            fp = os.path.join(self.test_dir, fname)
            if os.path.exists(fp):
                os.remove(fp)

    def _add(self, content, type="workflow", topics="[]", no_evolve=True):
        args = Namespace(type=type, content=content, topics=topics, no_evolve=no_evolve)
        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_add(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def _evolve(self):
        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_evolve(None)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def _load(self, limit=10):
        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_load(Namespace(limit=limit))
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def _search(self, keywords, limit=5):
        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_search(Namespace(keywords=keywords, limit=limit, offset=0))
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def _pc_path(self):
        return os.path.join(self.test_dir, "project-context.md")

    def _pc_text(self):
        path = self._pc_path()
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
        return None

    # ---- Full-chain tests ----------------------------------------------------

    def test_full_chain(self):
        """Add → Evolve → Load → Search full cycle."""
        # Step 1: Add
        rc, _ = self._add(content="WAL mode ensures crash safety",
                          type="architecture", topics='["sqlite","performance"]')
        self.assertEqual(rc, 0)

        # Step 2: Evolve
        rc, out = self._evolve()
        self.assertEqual(rc, 0)
        self.assertIn("进化完成", out)

        # Step 3: Verify project-context.md
        text = self._pc_text()
        self.assertIsNotNone(text)
        self.assertIn("<!-- evolve_seq:", text)
        self.assertIn("WAL mode ensures crash safety", text)
        self.assertIn("[architecture]", text)

        # Step 4: Load shows the entry
        rc, out = self._load(limit=10)
        self.assertEqual(rc, 0)
        self.assertIn("WAL mode ensures crash safety", out)

        # Step 5: FTS5 search works after evolve
        rc, out = self._search("WAL")
        self.assertEqual(rc, 0)
        self.assertIn("WAL mode ensures crash safety", out)

    # ---- Correction loop -----------------------------------------------------

    def test_correction_loop_delete(self):
        """Add → evolve → delete → evolve shows deletion in output."""
        # Add two entries
        self._add(content="original entry", type="tip")
        self._add(content="stable entry", type="tip")
        self._evolve()

        text = self._pc_text()
        self.assertIn("original entry", text)
        self.assertIn("stable entry", text)

        # Delete one entry
        old = sys.stdout; sys.stdout = StringIO()
        try:
            mem.cmd_delete(Namespace(seq=1))
        finally:
            sys.stdout = old

        # Evolve again
        self._evolve()

        text = self._pc_text()
        self.assertIn("已删除", text)
        self.assertIn("original entry", text)
        self.assertIn("stable entry", text)

    def test_correction_loop_update(self):
        """Add → evolve → update → evolve shows updated content."""
        self._add(content="old content", type="tip")
        self._evolve()

        text = self._pc_text()
        self.assertIn("old content", text)

        # Update entry
        old = sys.stdout; sys.stdout = StringIO()
        try:
            mem.cmd_update(Namespace(seq=1, content="updated content",
                                     type=None, topics=None))
        finally:
            sys.stdout = old

        self._evolve()
        text = self._pc_text()
        self.assertIn("updated content", text)

    # ---- Consecutive evolves -------------------------------------------------

    def test_consecutive_evolves(self):
        """Multiple evolve rounds with new data each time."""
        self._add(content="batch 1 entry", type="tip")
        rc, out = self._evolve()
        self.assertIn("进化完成 (V=1)", out)

        self._add(content="batch 2 entry", type="tip")
        rc, out = self._evolve()
        self.assertIn("进化完成 (V=2)", out)

        # Both entries should appear
        text = self._pc_text()
        self.assertIn("batch 1 entry", text)
        self.assertIn("batch 2 entry", text)

    # ---- Auto-evolve trigger -------------------------------------------------

    def test_auto_evolve_trigger(self):
        """cmd_add triggers auto-evolve when threshold reached."""
        with open(mem.CONFIG_PATH, "w") as f:
            f.write("auto_evolve_enabled = true\n")
            f.write("auto_evolve_threshold = 3\n")

        # Add 3 entries (at threshold)
        for i in range(3):
            rc, out = self._add(content=f"auto entry {i}", type="tip",
                                no_evolve=False)
            self.assertEqual(rc, 0)

        # Auto-evolve should have been triggered
        text = self._pc_text()
        self.assertIsNotNone(text)
        self.assertIn("auto entry", text)

    # ---- FTS5 after evolve ---------------------------------------------------

    def test_fts5_after_evolve(self):
        """FTS5 search still finds entries after evolve sets consolidated_seq."""
        self._add(content="fts5 persistence test", type="tip")
        self._add(content="unrelated content", type="tip")
        self._evolve()

        # Search should still work
        rc, out = self._search("fts5 persistence")
        self.assertEqual(rc, 0)
        self.assertIn("fts5 persistence test", out)

    # ---- Evolve with no unmerged data ----------------------------------------

    def test_evolve_idempotent(self):
        """Evolve on already-consolidated data succeeds and preserves entries."""
        self._add(content="idempotent test", type="tip")
        self._evolve()

        # Second evolve should succeed and preserve entries in project-context.md
        rc, out = self._evolve()
        self.assertEqual(rc, 0)
        self.assertIn("进化完成", out)
        text = self._pc_text()
        self.assertIsNotNone(text)
        self.assertIn("idempotent test", text)

    # ---- Load with stale project-context -------------------------------------

    def test_load_stale_warning(self):
        """Load warns when project-context.md evolve_seq is behind database."""
        # Create project-context.md with older evolve_seq
        pc_path = self._pc_path()
        with open(pc_path, "w") as f:
            f.write("<!-- evolve_seq: 0 -->\n\n# Old context\n")

        # Update db evolve_seq to 5
        db = mem.init_db()
        db.execute("UPDATE system SET value='5' WHERE key='evolve_seq'")
        db.commit()
        db.close()

        rc, out = self._load()
        self.assertEqual(rc, 0)
        self.assertIn("已过期", out)

    # ---- Export after evolve -------------------------------------------------

    def test_export_after_evolve(self):
        """Export works correctly after entries have been evolved."""
        self._add(content="export after evolve", type="tip")
        self._evolve()

        export_dir = os.path.join(self.test_dir, "export_after")
        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_export(Namespace(dir=export_dir))
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        files = [f for f in os.listdir(export_dir) if f != "_index.md"]
        self.assertGreater(len(files), 0)
        self.assertTrue(os.path.exists(os.path.join(export_dir, "_index.md")))

    # ---- Status after evolve -------------------------------------------------

    def test_status_after_evolve(self):
        """Status shows correct evolve version after evolve."""
        self._add(content="status evolve test", type="tip")
        self._evolve()

        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_status(None)
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        self.assertIn("v1", out)
        self.assertIn("总记录", out)


if __name__ == "__main__":
    unittest.main()
