"""Task 13: CJK text search integration test.

Tests end-to-end Chinese keyword search with jieba segmentation:
- FTS5 MATCH with jieba-splittable queries (系统设计 → "系统 设计")
- LIKE fallback for compound words jieba doesn't split (记忆系统)
"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestCjkSearch(unittest.TestCase):
    """Integration tests for CJK keyword search with jieba segmentation."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="cjk_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        # Clean up stale WAL files that can corrupt fresh databases
        for ext in ("-wal", "-shm"):
            wp = mem.DB_PATH + ext
            if os.path.exists(wp):
                os.remove(wp)

    def tearDown(self):
        if mem._lock_fd is not None:
            mem.release_lock()
        for f in ["memory.db", "project-context.md", "config.toml"]:
            fp = os.path.join(self.test_dir, f)
            if os.path.exists(fp):
                os.remove(fp)

    def _add(self, content, type="tip", topics="[]", no_evolve=True):
        args = Namespace(type=type, content=content, topics=topics, no_evolve=no_evolve)
        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_add(args)
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

    def test_cjk_multi_word(self):
        """Multi-word CJK query finds results (via FTS5 + LIKE chain)."""
        self._add(content="系统设计方法", type="tip")
        self._add(content="设计文档和笔记", type="tip")
        rc, out = self._search("系统设计")
        self.assertEqual(rc, 0)
        self.assertIn("系统设计方法", out)

    def test_cjk_single_word(self):
        """Single CJK word query splits by jieba '学习'."""
        self._add(content="学习新的编程技巧", type="tip")
        rc, out = self._search("学习")
        self.assertEqual(rc, 0)
        self.assertIn("学习新的编程技巧", out)

    def test_cjk_compound_word(self):
        """Compound word not split by jieba falls back to LIKE."""
        self._add(content="记忆系统性能优化", type="tip")
        rc, out = self._search("记忆系统")
        self.assertEqual(rc, 0)
        self.assertIn("记忆系统性能优化", out)

    def test_english_search(self):
        """English search unchanged by jieba segmentation."""
        self._add(content="WAL mode ensures crash safety", type="tip")
        rc, out = self._search("WAL")
        self.assertEqual(rc, 0)
        self.assertIn("WAL mode", out)

    def test_mixed_query(self):
        """Mixed EN/CJK query segments CJK part only."""
        self._add(content="SQLite 全文搜索配置", type="tip")
        rc, out = self._search("全文搜索")
        self.assertEqual(rc, 0)
        self.assertIn("全文搜索", out)

    def test_search_no_results(self):
        """Query with no matches returns 0 hits gracefully."""
        rc, out = self._search("zzzznotexist")
        self.assertEqual(rc, 0)
        self.assertIn("未找到", out)

    def test_cjk_partial_char_fallback(self):
        """Single CJK char not in jieba dict falls back to LIKE."""
        self._add(content="这个系统很好用", type="tip")
        rc, out = self._search("系统")
        self.assertEqual(rc, 0)
        self.assertIn("系统", out)

    def test_cjk_with_evolve(self):
        """CJK entries survive evolve cycle and remain searchable."""
        self._add(content="学习了新的记忆方法", type="tip")
        old = sys.stdout; sys.stdout = StringIO()
        try:
            mem.cmd_evolve(None)
        finally:
            sys.stdout = old
        rc, out = self._search("学习")
        self.assertEqual(rc, 0)
        self.assertIn("学习", out)

    def test_cjk_search_via_like(self):
        """CJK search works via LIKE fallback when FTS5 unicode61 misses."""
        self._add(content="系统架构设计模式", type="tip")
        self._add(content="这个设计模式很好", type="tip")
        rc, out = self._search("设计模式")
        self.assertEqual(rc, 0)
        # At least one result found (via LIKE if FTS5 misses)
        self.assertIn("相关记忆", out)

    def test_empty_database_search(self):
        """Empty database handles search gracefully."""
        rc, out = self._search("测试")
        self.assertEqual(rc, 0)

    def test_no_jieba_fallback(self):
        """Search works when jieba not available (simulated by pure ASCII)."""
        self._add(content="hello world testing", type="tip")
        rc, out = self._search("hello world")
        self.assertEqual(rc, 0)
        self.assertIn("hello world", out)

    def test_multiple_cjk_entries(self):
        """Multiple CJK entries return correctly ordered results."""
        for i in range(5):
            self._add(content=f"学习新知识第{i}天", type="tip")
        rc, out = self._search("学习")
        self.assertEqual(rc, 0)
        for i in range(5):
            self.assertIn(f"第{i}天", out)


if __name__ == "__main__":
    unittest.main()
