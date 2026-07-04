"""Chinese text segmentation via jieba (optional dependency).

Provides jieba-based segmentation for FTS5 indexing of Chinese text.
FTS5's unicode61 tokenizer treats each CJK character as a separate token,
which misses multi-character word boundaries. Jieba segments text into
Chinese words, improving search accuracy.

Usage:
    import seg
    if seg.is_available():
        tokens = seg.segment("系统设计")   # → "系统 设计"
        query = seg.maybe_segment("系统")  # → "系统"
"""

import re
import sys

# Module-level cache for jieba availability
_HAS_JIEBA = None

# CJK Unicode ranges covering common East-Asian scripts
# Includes: CJK Extension A-F, Unified Ideographs, Compatibility Ideographs,
# Hiragana, Katakana, and Hangul Syllables.
_CJK_RE = re.compile(
    r"[\u3400-\u4dbf"          # CJK Extension A
    r"\u4e00-\u9fff"           # CJK Unified Ideographs
    r"\uf900-\ufaff"           # CJK Compatibility Ideographs
    r"\U00020000-\U0002a6df"   # CJK Extension B
    r"\U0002a700-\U0002b73f"   # CJK Extension C
    r"\U0002b740-\U0002b81f"   # CJK Extension D
    r"\U0002b820-\U0002ceaf"   # CJK Extension E
    r"\U0002ceb0-\U0002ebef"   # CJK Extension F
    r"\u3040-\u309f"           # Hiragana
    r"\u30a0-\u30ff"           # Katakana
    r"\uac00-\ud7af"           # Hangul Syllables
    r"]"
)

_JIEBA_INITIALIZED = False


def _check_jieba():
    """Check if jieba is importable. Result cached module-wide."""
    global _HAS_JIEBA
    if _HAS_JIEBA is None:
        try:
            import jieba  # noqa: F401
            _HAS_JIEBA = True
        except ImportError:
            _HAS_JIEBA = False
    return _HAS_JIEBA


def _ensure_jieba_initialized():
    """Ensure jieba dictionary is loaded (synchronous, ~200ms first call)."""
    global _JIEBA_INITIALIZED
    if not _JIEBA_INITIALIZED:
        import jieba
        jieba.initialize()
        _JIEBA_INITIALIZED = True


def is_available():
    """Return True if jieba is installed and importable.

    Result is cached module-wide after first check.
    """
    return _check_jieba()


def has_cjk(text):
    """Return True if text contains any CJK character.

    Covers CJK Unified Ideographs, Extension A-F, Compatibility
    Ideographs, Hiragana, Katakana, and Hangul Syllables.
    """
    return bool(_CJK_RE.search(text))


def segment(text):
    """Segment text with jieba into space-separated tokens.

    Args:
        text: Input string (may contain CJK).

    Returns:
        Space-separated token string, e.g. "系统 设计".
        Falls back to original text if jieba unavailable or
        segmentation fails.
    """
    if not text:
        return text
    try:
        if not _check_jieba():
            return text
    except Exception:
        return text
    try:
        _ensure_jieba_initialized()
        import jieba
        return " ".join(jieba.cut(text, cut_all=False))
    except Exception as exc:
        print(f"\u26a0 \u4e2d\u6587\u5206\u8bcd\u5931\u8d25: {exc}",
              file=sys.stderr)
        return text


def maybe_segment(text):
    """Segment text only if it contains CJK characters and jieba is available.

    For pure ASCII or mixed queries without CJK, returns original text
    unchanged to avoid unnecessary processing.
    """
    if not has_cjk(text):
        return text
    try:
        if _check_jieba():
            return segment(text)
    except Exception:
        pass
    return text
