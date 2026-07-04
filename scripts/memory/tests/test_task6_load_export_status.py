"""Task 6: memory load + export + status 单元测试"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestLoadExportStatus(unittest.TestCase):
    """Test load, export, and status commands."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="load_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        for fname in ["profile.md", "project-context.md"]:
            fp = os.path.join(self.test_dir, fname)
            if os.path.exists(fp):
                os.remove(fp)
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _add(self, content, type="workflow", topics="[]"):
        args = Namespace(type=type, content=content, topics=topics, no_evolve=True)
        mem.cmd_add(args)

    def _run(self, func, **kwargs):
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            rc = func(Namespace(**kwargs))
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def test_load_no_files(self):
        rc, out = self._run(mem.cmd_load, limit=10)
        self.assertEqual(rc, 0)

    def test_load_shows_entries(self):
        self._add("load test entry")
        rc, out = self._run(mem.cmd_load, limit=10)
        self.assertEqual(rc, 0)
        self.assertIn("load test entry", out)

    def test_load_profile(self):
        pf = os.path.join(self.test_dir, "profile.md")
        with open(pf, "w") as f:
            f.write("# profile content here")
        rc, out = self._run(mem.cmd_load, limit=10)
        self.assertIn("profile content here", out)

    def test_load_stale(self):
        pc = os.path.join(self.test_dir, "project-context.md")
        with open(pc, "w") as f:
            f.write("<!-- evolve_seq: 0 -->\n\n# Stale")
        self.db.execute("UPDATE system SET value='5' WHERE key='evolve_seq'")
        self.db.commit()
        rc, out = self._run(mem.cmd_load, limit=10)
        self.assertEqual(rc, 0)

    def test_export_empty(self):
        rc, out = self._run(mem.cmd_export, dir=os.path.join(self.test_dir, "export"))
        self.assertEqual(rc, 0)
        ed = os.path.join(self.test_dir, "export")
        self.assertTrue(os.path.exists(os.path.join(ed, "_index.md")))

    def test_export_creates_files(self):
        self._add("export content")
        ed = os.path.join(self.test_dir, "export")
        rc, out = self._run(mem.cmd_export, dir=ed)
        self.assertEqual(rc, 0)
        files = [f for f in os.listdir(ed) if f != "_index.md"]
        self.assertGreater(len(files), 0)
        text = open(os.path.join(ed, files[0])).read()
        self.assertIn("export content", text)

    def test_export_with_types(self):
        self._add("workflow test", type="workflow")
        self._add("bug test", type="bug")
        ed = os.path.join(self.test_dir, "export")
        rc, out = self._run(mem.cmd_export, dir=ed)
        self.assertEqual(rc, 0)
        files = [f for f in os.listdir(ed) if f != "_index.md"]
        self.assertGreaterEqual(len(files), 2)

    def test_status_empty(self):
        rc, out = self._run(mem.cmd_status)
        self.assertEqual(rc, 0)
        self.assertIn("总记录", out)

    def test_status_with_entries(self):
        self._add("status test")
        rc, out = self._run(mem.cmd_status)
        self.assertEqual(rc, 0)
        self.assertIn("有效: 1", out)

    def test_status_after_evolve(self):
        self._add("evolve status test")
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            mem.cmd_evolve(Namespace())
        finally:
            sys.stdout = old
        rc, out = self._run(mem.cmd_status)
        self.assertEqual(rc, 0)
        self.assertIn("v1", out)


if __name__ == "__main__":
    unittest.main()
