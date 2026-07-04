"""Task 3: memory search + list 单元测试"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestSearchList(unittest.TestCase):
    """Test search and list commands."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="search_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _add(self, content, add_type="workflow", topics="[]"):
        args = Namespace(type=add_type, content=content, topics=topics, no_evolve=True)
        mem.cmd_add(args)

    def _search(self, keywords, limit=5, offset=0):
        args = Namespace(keywords=keywords, limit=limit, offset=offset)
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            rc = mem.cmd_search(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def _list(self, limit=10):
        args = Namespace(limit=limit)
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            rc = mem.cmd_list(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old

    def test_search_fts5_match(self):
        self._add("hello world unique_keyword_1")
        rc, out = self._search("unique_keyword_1")
        self.assertEqual(rc, 0)
        self.assertIn("hello world", out)

    def test_search_no_results(self):
        rc, out = self._search("this_should_not_match_xyz")
        self.assertEqual(rc, 0)
        self.assertIn("未找到", out)

    def test_search_like_fallback(self):
        self._add("like_fallback_special_string")
        rc, out = self._search("like_fallback_special_string")
        self.assertEqual(rc, 0)
        self.assertIn("like_fallback_special_string", out)

    def test_list_with_entries(self):
        for i in range(3):
            self._add(f"list_item_{i}")
        rc, out = self._list()
        self.assertEqual(rc, 0)
        for i in range(3):
            self.assertIn(f"list_item_{i}", out)

    def test_list_empty(self):
        rc, out = self._list()
        self.assertEqual(rc, 0)
        self.assertIn("暂无", out)

    def test_search_limit(self):
        for i in range(5):
            self._add(f"limit_test_{i}")
        rc, out = self._search("limit_test", limit=2)
        self.assertEqual(rc, 0)
        # should only show 2 results
        count = out.count("limit_test_")
        self.assertEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
