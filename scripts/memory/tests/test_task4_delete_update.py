"""Task 4: memory delete + update 单元测试"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace
from io import StringIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestDeleteUpdate(unittest.TestCase):
    """Test delete and update commands."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="delupd_test_")

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

    def _assert_stdout(self, func, args, expected_rc=None, expected_substr=None):
        old = sys.stdout
        sys.stdout = StringIO()
        try:
            rc = func(args)
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        if expected_rc is not None:
            self.assertEqual(rc, expected_rc)
        if expected_substr:
            self.assertIn(expected_substr, out)
        return rc, out

    def test_delete_success(self):
        mem.cmd_add(Namespace(type="workflow", content="delete me", topics="[]", no_evolve=True))
        seq = self.db.execute("SELECT seq FROM entries WHERE content='delete me'").fetchone()["seq"]
        self._assert_stdout(
            mem.cmd_delete, Namespace(seq=seq),
            expected_rc=0, expected_substr="已删除",
        )
        row = self.db.execute("SELECT deleted FROM entries WHERE seq=?", (seq,)).fetchone()
        self.assertEqual(row["deleted"], 1)

    def test_delete_not_found(self):
        self._assert_stdout(
            mem.cmd_delete, Namespace(seq=9999),
            expected_rc=1, expected_substr="未找到",
        )

    def test_delete_triggers_correction(self):
        mem.cmd_add(Namespace(type="workflow", content="correcting", topics="[]", no_evolve=True))
        seq = self.db.execute("SELECT seq FROM entries WHERE content='correcting'").fetchone()["seq"]
        self.db.execute("UPDATE entries SET consolidated_seq=1 WHERE seq=?", (seq,))
        self.db.commit()
        self._assert_stdout(mem.cmd_delete, Namespace(seq=seq), expected_rc=0)
        cc = self.db.execute("SELECT correction_count FROM entries WHERE seq=?", (seq,)).fetchone()["correction_count"]
        self.assertGreaterEqual(cc, 1)
        tc = self.db.execute("SELECT value FROM system WHERE key='total_corrections'").fetchone()["value"]
        self.assertGreaterEqual(int(tc), 1)

    def test_update_success(self):
        mem.cmd_add(Namespace(type="workflow", content="old content", topics="[]", no_evolve=True))
        seq = self.db.execute("SELECT seq FROM entries WHERE content='old content'").fetchone()["seq"]
        self._assert_stdout(
            mem.cmd_update, Namespace(seq=seq, content="new content", type=None, topics=None),
            expected_rc=0, expected_substr="已更新",
        )
        row = self.db.execute("SELECT content FROM entries WHERE seq=?", (seq,)).fetchone()
        self.assertEqual(row["content"], "new content")

    def test_update_not_found(self):
        self._assert_stdout(
            mem.cmd_update, Namespace(seq=9999, content="x", type=None, topics=None),
            expected_rc=1, expected_substr="未找到",
        )

    def test_update_collision(self):
        mem.cmd_add(Namespace(type="workflow", content="first", topics="[]", no_evolve=True))
        mem.cmd_add(Namespace(type="workflow", content="second", topics="[]", no_evolve=True))
        seq2 = self.db.execute("SELECT seq FROM entries WHERE content='second'").fetchone()["seq"]
        self._assert_stdout(
            mem.cmd_update, Namespace(seq=seq2, content="first", type=None, topics=None),
            expected_rc=1, expected_substr="冲突",
        )

    def test_update_triggers_correction(self):
        mem.cmd_add(Namespace(type="workflow", content="fix me", topics="[]", no_evolve=True))
        seq = self.db.execute("SELECT seq FROM entries WHERE content='fix me'").fetchone()["seq"]
        self.db.execute("UPDATE entries SET consolidated_seq=5 WHERE seq=?", (seq,))
        self.db.commit()
        self._assert_stdout(
            mem.cmd_update, Namespace(seq=seq, content="fixed", type=None, topics=None),
            expected_rc=0,
        )
        cc = self.db.execute("SELECT correction_count FROM entries WHERE seq=?", (seq,)).fetchone()["correction_count"]
        self.assertGreaterEqual(cc, 1)


if __name__ == "__main__":
    unittest.main()
