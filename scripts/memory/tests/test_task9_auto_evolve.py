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


class TestAutoEvolve(unittest.TestCase):
    """Auto-evolve trigger in cmd_add."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="auto_evolve_")
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
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
        self.assertIn("<!-- evolve_seq:", content)
        self.assertIn("entry 0", content)
        self.assertIn("entry 1", content)
        self.assertIn("entry 2", content)


if __name__ == "__main__":
    unittest.main()
