"""Task 7: memory vec + migrate 单元测试"""

import sys, os, tempfile, shutil, json, unittest
from argparse import Namespace
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestVec(unittest.TestCase):
    """Test vec commands."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="vec_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        jl = os.path.join(self.test_dir, "learnings.jsonl")
        if os.path.exists(jl):
            os.remove(jl)

    def _run(self, func, **kwargs):
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            rc = func(Namespace(**kwargs))
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def test_vec_status_no_model(self):
        rc, out = self._run(mem.cmd_vec, vec_cmd="status")
        self.assertEqual(rc, 0)
        self.assertIn("向量", out)

    def test_vec_enable(self):
        """vec enable downloads model and indexes entries."""
        rc = mem.cmd_vec(Namespace(vec_cmd="enable"))
        self.assertEqual(rc, 0)

    def test_vec_rebuild(self):
        """vec rebuild clears and re-indexes."""
        rc = mem.cmd_vec(Namespace(vec_cmd="rebuild"))
        self.assertEqual(rc, 0)


class TestMigrate(unittest.TestCase):
    """Test migrate command."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="migrate_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        jl = os.path.join(self.test_dir, "learnings.jsonl")
        if os.path.exists(jl):
            os.remove(jl)

    def _run(self, func, **kwargs):
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            rc = func(Namespace(**kwargs))
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def test_migrate_no_file(self):
        rc, out = self._run(mem.cmd_migrate)
        self.assertEqual(rc, 1)
        self.assertIn("未找到", out)

    def test_migrate_imports_entries(self):
        jsonl_path = os.path.join(self.test_dir, "learnings.jsonl")
        entries = [
            {"ts": "2026-01-01", "type": "workflow", "content": "test entry 1", "topics": "codex,memory"},
            {"ts": "2026-01-02", "type": "architecture", "content": "test entry 2", "topics": "design"},
        ]
        with open(jsonl_path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        rc, out = self._run(mem.cmd_migrate)
        self.assertEqual(rc, 0)
        self.assertIn("已迁移 2", out)
        count = self.db.execute("SELECT count(*) FROM entries").fetchone()[0]
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
