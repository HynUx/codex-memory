"""seg module unit tests"""

import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import seg


class TestIsAvailable(unittest.TestCase):
    def test_available_with_jieba(self):
        """jieba installed => is_available() returns True."""
        self.assertTrue(seg.is_available())

    def test_available_type(self):
        self.assertIsInstance(seg.is_available(), bool)

    def test_cached(self):
        """Calling twice returns same result (module-level cache)."""
        self.assertEqual(seg.is_available(), seg.is_available())


class TestHasCJK(unittest.TestCase):
    def test_chinese_ideographs(self):
        self.assertTrue(seg.has_cjk("记忆系统"))
        self.assertTrue(seg.has_cjk("中文"))

    def test_mixed_text(self):
        self.assertTrue(seg.has_cjk("SQLite WAL 模式"))
        self.assertTrue(seg.has_cjk("hello世界"))

    def test_japanese_hiragana(self):
        self.assertTrue(seg.has_cjk("あいうえお"))

    def test_japanese_katakana(self):
        self.assertTrue(seg.has_cjk("アイウエオ"))

    def test_korean_hangul(self):
        self.assertTrue(seg.has_cjk("한글"))

    def test_ascii_only(self):
        self.assertFalse(seg.has_cjk("hello world"))
        self.assertFalse(seg.has_cjk("WAL mode"))
        self.assertFalse(seg.has_cjk(""))

    def test_numbers(self):
        self.assertFalse(seg.has_cjk("12345"))


class TestSegment(unittest.TestCase):
    def test_multi_word_phrase(self):
        """jieba splits multi-word phrases like '系统设计'."""
        result = seg.segment("系统设计")
        self.assertIn(" ", result)
        self.assertIn("系统", result)
        self.assertIn("设计", result)

    def test_single_word_compound(self):
        """jieba does NOT split single compound words like '记忆系统'."""
        result = seg.segment("记忆系统")
        # jieba treats this as a single word - no space
        self.assertEqual(result, "记忆系统")

    def test_mixed_content(self):
        """CJK+English mixed text preserves English."""
        result = seg.segment("SQLite WAL 模式")
        self.assertIn("SQLite", result)

    def test_empty_string(self):
        self.assertEqual(seg.segment(""), "")

    def test_ascii_only(self):
        """Pure ASCII returns unchanged."""
        result = seg.segment("hello world")
        self.assertIsNotNone(result)

    def test_none(self):
        """None input returns None (function should not crash)."""
        self.assertEqual(seg.segment(None), None)


class TestMaybeSegment(unittest.TestCase):
    def test_cjk_text_segmented(self):
        """CJK text should be segmented by jieba when available."""
        result = seg.maybe_segment("系统设计")
        self.assertIn(" ", result)

    def test_single_compound_cjk(self):
        """Single compound CJK word returns unchanged."""
        result = seg.maybe_segment("记忆系统")
        self.assertEqual(result, "记忆系统")

    def test_ascii_unchanged(self):
        """Pure ASCII returns original text unchanged."""
        result = seg.maybe_segment("hello world")
        self.assertEqual(result, "hello world")

    def test_empty_unchanged(self):
        self.assertEqual(seg.maybe_segment(""), "")

    def test_mixed_cjk_english(self):
        """Mixed text is still segmented (contains CJK)."""
        result = seg.maybe_segment("WAL 模式 vs SQLite")
        self.assertIn(" ", result)
        self.assertIn("模式", result)


if __name__ == "__main__":
    unittest.main()
