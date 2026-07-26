"""Task 9: Auto-evolve trigger 单元测试

Covers:
- Threshold triggers evolve when unmerged count is reached
- --no-evolve flag suppresses auto-evolve
- auto_evolve_enabled=false suppresses auto-evolve
- No evolve when unmerged is below threshold
"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem
import embed
from io import StringIO


def capture(fn):
    """Run fn and return (rc, stdout_output)."""
    old = sys.stdout
    sys.stdout = StringIO()
    try:
        rc = fn()
        return rc, sys.stdout.getvalue()
    finally:
        sys.stdout = old


class TestAutoEvolve(unittest.TestCase):
    """Auto-evolve trigger in cmd_add."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="auto_evolve_")
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        embed.set_faiss_dir(self.test_dir)
        mem.LOCK_PATH = os.path.join(self.test_dir, ".lock")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")

    def tearDown(self):
        # Ensure any stale lock fd is closed
        if mem._lock_fd is not None:
            mem.release_lock()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write_config(self, **overrides):
        """Write config.toml with overrides (default threshold=3)."""
        config = {"auto_evolve_enabled": "true", "auto_evolve_threshold": "3"}
        config.update(overrides)
        with open(mem.CONFIG_PATH, "w") as f:
            for k, v in config.items():
                f.write(f"{k} = {v}\n")

    def _pc_path(self):
        return os.path.join(self.test_dir, "project-context.md")

    def _backup_dir(self):
        return os.path.join(self.test_dir, ".backup")

    def test_below_threshold_no_evolve(self):
        """Adding below threshold does not trigger evolve."""
        self._write_config(auto_evolve_threshold="5")
        for i in range(3):
            mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=False,
            ))
        self.assertFalse(os.path.exists(self._pc_path()))

    def test_at_threshold_triggers_evolve(self):
        """Adding at threshold triggers evolve (project-context.md created)."""
        self._write_config(auto_evolve_threshold="3")
        for i in range(3):
            mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=False,
            ))
        self.assertTrue(os.path.exists(self._pc_path()))
        # Also verify backup dir exists
        self.assertTrue(os.path.exists(self._backup_dir()))

    def test_no_evolve_flag_suppresses(self):
        """--no-evolve flag suppresses auto-evolve even at threshold."""
        self._write_config(auto_evolve_threshold="3")
        for i in range(3):
            mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=True,
            ))
        self.assertFalse(os.path.exists(self._pc_path()))

    def test_disabled_in_config(self):
        """auto_evolve_enabled=false suppresses auto-evolve."""
        self._write_config(auto_evolve_enabled="false", auto_evolve_threshold="3")
        for i in range(3):
            mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=False,
            ))
        self.assertFalse(os.path.exists(self._pc_path()))

    def test_evolve_content_contains_entries(self):
        """Auto-evolved project-context.md contains the added entries."""
        self._write_config(auto_evolve_threshold="3")
        for i in range(3):
            mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=False,
            ))
        with open(self._pc_path()) as f:
            content = f.read()
        self.assertRegex(content, r"<!-- evolve_seq: \d+ -->")
        self.assertIn("entry 0", content)
        self.assertIn("entry 1", content)
        self.assertIn("entry 2", content)



    def test_missing_config_falls_back_to_defaults(self):
        """No config.toml -> defaults used, no crash."""
        self._write_config(auto_evolve_threshold="3")
        os.remove(mem.CONFIG_PATH)
        for i in range(3):
            mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=False,
            ))
        # With no config, threshold=20, 3 entries below threshold, no evolve
        self.assertFalse(os.path.exists(self._pc_path()))

    def test_non_numeric_threshold_no_crash(self):
        """Invalid threshold value uses default, no TypeError."""
        with open(mem.CONFIG_PATH, "w") as f:
            f.write("auto_evolve_threshold = invalid\n")
            f.write("auto_evolve_enabled = true\n")
        for i in range(3):
            rc = mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=False,
            ))
            self.assertEqual(rc, 0, "add should not crash on invalid config")
        self.assertFalse(os.path.exists(self._pc_path()))

    def test_quoted_config_values(self):
        """TOML-style quoted values parsed correctly."""
        with open(mem.CONFIG_PATH, "w") as f:
            f.write('auto_evolve_threshold = "3"\n')
            f.write('auto_evolve_enabled = "true"\n')
        for i in range(3):
            mem.cmd_add(Namespace(
                type="tip", content=f"entry {i}", topics="[]", no_evolve=False,
            ))
        self.assertTrue(os.path.exists(self._pc_path()),
                        "quoted true/3 should trigger evolve")




class TestThresholdGuard(unittest.TestCase):
    """Test that cmd_evolve respects threshold when called from CLI (not --force)."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="evolve_guard_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        embed.set_faiss_dir(self.test_dir)
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _add(self, content):
        mem.cmd_add(Namespace(type="tip", content=content, topics="[]", no_evolve=True))

    def test_evolve_skips_below_threshold(self):
        """CLI evolve (no --force) skips when unmerged < threshold."""
        self._add("single entry")
        rc, out = capture(lambda: mem.cmd_evolve(Namespace(force=False)))
        self.assertEqual(rc, 0)
        self.assertIn("不足", out)

    def test_evolve_force_always_works(self):
        """CLI evolve --force always evolves regardless of threshold."""
        self._add("single entry")
        rc, out = capture(lambda: mem.cmd_evolve(Namespace(force=True)))
        self.assertEqual(rc, 0)
        self.assertIn("进化完成", out)

    def test_evolve_programmatic_skips_guard(self):
        """Programmatic evolve (args=None) always evolves."""
        self._add("single entry")
        rc, out = capture(lambda: mem.cmd_evolve(None))
        self.assertEqual(rc, 0)
        self.assertIn("进化完成", out)


if __name__ == "__main__":
    unittest.main()
