"""Task 10: memory review + config + vec_rebuild 单元测试"""

import sys, os, tempfile, shutil, unittest
import argparse
from argparse import Namespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem
import embed


class TestCmdConfig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="config_test_")
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)
    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.CONFIG_PATH):
            os.remove(mem.CONFIG_PATH)

    def test_config_show_no_file(self):
        from io import StringIO
        old = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_config(Namespace(config_cmd="show", model=None))
            out = sys.stdout.getvalue()
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        self.assertIn("deepseek-v4-flash", out)

    def test_config_set_model_valid(self):
        rc = mem.cmd_config(Namespace(config_cmd="set-model", model="qwen3.7-plus"))
        self.assertEqual(rc, 0)
        with open(mem.CONFIG_PATH) as f:
            self.assertIn("learner_model = qwen3.7-plus", f.read())

    def test_config_set_model_invalid(self):
        self.assertEqual(mem.cmd_config(Namespace(config_cmd="set-model", model="bad")), 1)

    def test_config_set_model_preserves_comments(self):
        with open(mem.CONFIG_PATH, "w") as f:
            f.write("# a comment\nauto_evolve_enabled = false\n")
        mem.cmd_config(Namespace(config_cmd="set-model", model="deepseek-v4-flash"))
        with open(mem.CONFIG_PATH) as f:
            self.assertTrue(any("# a comment" in l for l in f.readlines()))


class TestVecRebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="vecrebuild_test_")
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

    def test_rebuild_no_entries(self):
        mem._vec_rebuild(self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM entries_vec").fetchone()[0], 0)

    def test_rebuild_no_crash(self):
        self.db.execute("INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)",
                        ("tip", "t", "[]", "a1"))
        self.db.commit()
        mem._vec_rebuild(self.db)


    def test_config_has_parser(self):
        parser = mem.build_parser()
        sub = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)][0]
        self.assertIn("config", sub.choices)


class TestAvailableModels(unittest.TestCase):
    def test_has_models(self):
        self.assertIn("deepseek-v4-flash", mem.AVAILABLE_MODELS)
    def test_default_model(self):
        self.assertEqual(mem.DEFAULT_LEARNER_MODEL, "deepseek-v4-flash")


class TestReviewCmd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="review_test_")
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

    def test_review_default_is_list(self):
        rc = mem.cmd_review(Namespace(review_cmd="list", limit=10, seq=None))
        self.assertEqual(rc, 0)

    def test_review_mark(self):
        self.db.execute("INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)",
                        ("tip", "rm", "[]", "rr1"))
        self.db.commit()
        seq = self.db.execute("SELECT seq FROM entries WHERE sha256='rr1'").fetchone()[0]
        self.assertEqual(mem.cmd_review(Namespace(review_cmd="mark", seq=seq, limit=10)), 0)
        proc = self.db.execute("SELECT llm_processed_at FROM entries WHERE seq=?", (seq,)).fetchone()[0]
        self.assertIsNotNone(proc)

    def test_review_list_json(self):
        self.db.execute("INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)",
                        ("tip", "rj", "[]", "rj1"))
        self.db.commit()
        from io import StringIO
        old = sys.stdout; sys.stdout = StringIO()
        try:
            mem.cmd_review(Namespace(review_cmd="list", limit=10, seq=None))
            import json
            data = json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = old
        self.assertIn("model", data)
        self.assertEqual(data["model"], mem.DEFAULT_LEARNER_MODEL)
