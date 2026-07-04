"""Task 12: entity/belief/relation CLI commands 单元测试"""

import sys, os, tempfile, shutil, unittest
from argparse import Namespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestEntityAdd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="entity_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _add(self, name="test-entity", etype="person", values=None):
        kwargs = {"name": name, "type": etype, "entity_cmd": "add", "values": values}
        args = Namespace(**kwargs)
        from io import StringIO
        old_out = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_entity_add(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old_out

    def test_add_success(self):
        rc, out = self._add()
        self.assertEqual(rc, 0)
        self.assertIn("✓", out)
        row = self.db.execute("SELECT id, name, type, entity_values FROM entities").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "test-entity")
        self.assertEqual(row["type"], "person")
        self.assertEqual(row["entity_values"], "[]")

    def test_add_with_values(self):
        rc, out = self._add(values='[{"key": "url", "value": "https://example.com"}]')
        self.assertEqual(rc, 0)
        row = self.db.execute("SELECT entity_values FROM entities WHERE name='test-entity'").fetchone()
        self.assertIn("url", row["entity_values"])

    def test_add_duplicate(self):
        self._add()
        rc, out = self._add()
        self.assertIn("⏭", out)
        rows = self.db.execute("SELECT count(*) FROM entities").fetchone()
        self.assertEqual(rows[0], 1)

    def test_add_empty_name(self):
        rc, out = self._add(name="")
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_empty_type(self):
        rc, out = self._add(etype="")
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_different_type_same_name(self):
        self._add(name="alice", etype="person")
        rc, out = self._add(name="alice", etype="bot")
        self.assertEqual(rc, 0)
        self.assertIn("✓", out)
        rows = self.db.execute("SELECT count(*) FROM entities").fetchone()
        self.assertEqual(rows[0], 2)


class TestEntityList(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="entitylist_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _list(self):
        args = Namespace()
        from io import StringIO
        old_out = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_entity_list(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old_out

    def test_list_empty(self):
        rc, out = self._list()
        self.assertEqual(rc, 0)
        self.assertIn("暂无", out)

    def test_list_with_entities(self):
        self.db.execute("INSERT INTO entities(name, type) VALUES('a', 'person')")
        self.db.execute("INSERT INTO entities(name, type) VALUES('b', 'org')")
        self.db.commit()
        rc, out = self._list()
        self.assertEqual(rc, 0)
        self.assertIn("a", out)
        self.assertIn("b", out)


class TestBeliefAdd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="belief_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _add(self, content="A believes B", source_seqs=None, confidence=None):
        kwargs = {"content": content}
        if source_seqs is not None:
            kwargs["source_seqs"] = source_seqs
        if confidence is not None:
            kwargs["confidence"] = confidence
        args = Namespace(**kwargs)
        from io import StringIO
        old_out = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_belief_add(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old_out

    def test_add_success(self):
        rc, out = self._add()
        self.assertEqual(rc, 0)
        self.assertIn("✓", out)
        row = self.db.execute(
            "SELECT id, content, source_seqs, confidence, evolve_seq FROM beliefs"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["content"], "A believes B")
        self.assertEqual(row["source_seqs"], "[]")
        self.assertEqual(row["confidence"], 0.5)
        self.assertEqual(row["evolve_seq"], 0)

    def test_add_with_source_seqs(self):
        rc, out = self._add(source_seqs="[1,2,3]")
        self.assertEqual(rc, 0)
        row = self.db.execute("SELECT source_seqs FROM beliefs WHERE content='A believes B'").fetchone()
        self.assertEqual(row["source_seqs"], "[1,2,3]")

    def test_add_with_confidence(self):
        rc, out = self._add(confidence=0.9)
        self.assertEqual(rc, 0)
        row = self.db.execute("SELECT confidence FROM beliefs WHERE content='A believes B'").fetchone()
        self.assertEqual(row["confidence"], 0.9)

    def test_add_empty_content(self):
        rc, out = self._add(content="")
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_invalid_confidence_high(self):
        rc, out = self._add(confidence=1.5)
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_invalid_confidence_low(self):
        rc, out = self._add(confidence=-0.1)
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_evolve_seq_match(self):
        # Bump evolve_seq to verify belief picks it up
        self.db.execute("UPDATE system SET value='5' WHERE key='evolve_seq'")
        self.db.commit()
        rc, out = self._add()
        self.assertEqual(rc, 0)
        row = self.db.execute("SELECT evolve_seq FROM beliefs WHERE content='A believes B'").fetchone()
        self.assertEqual(row["evolve_seq"], 5)

    def test_add_increments_id(self):
        for i in range(3):
            self._add(content=f"belief {i}")
        ids = [r["id"] for r in self.db.execute(
            "SELECT id FROM beliefs ORDER BY id").fetchall()]
        self.assertEqual(ids, [1, 2, 3])


class TestBeliefList(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="belieflist_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _list(self):
        args = Namespace()
        from io import StringIO
        old_out = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_belief_list(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old_out

    def test_list_empty(self):
        rc, out = self._list()
        self.assertEqual(rc, 0)
        self.assertIn("暂无", out)

    def test_list_with_beliefs(self):
        self.db.execute(
            "INSERT INTO beliefs(content, source_seqs, confidence, evolve_seq) VALUES('b1', '[]', 0.5, 0)"
        )
        self.db.execute(
            "INSERT INTO beliefs(content, source_seqs, confidence, evolve_seq) VALUES('b2', '[1]', 0.8, 1)"
        )
        self.db.commit()
        rc, out = self._list()
        self.assertEqual(rc, 0)
        self.assertIn("b1", out)
        self.assertIn("b2", out)


class TestRelationAdd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="relation_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()
        # Create test entities for relation tests
        self.db.execute("INSERT INTO entities(id, name, type) VALUES(1, 'Alice', 'person')")
        self.db.execute("INSERT INTO entities(id, name, type) VALUES(2, 'Bob', 'person')")
        self.db.execute("INSERT INTO entities(id, name, type) VALUES(3, 'Codex', 'tool')")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _add(self, subject_id=1, predicate="knows", object_id=2, source_seq=None):
        kwargs = {
            "subject_id": subject_id,
            "predicate": predicate,
            "object_id": object_id,
        }
        if source_seq is not None:
            kwargs["source_seq"] = source_seq
        args = Namespace(**kwargs)
        from io import StringIO
        old_out = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_relation_add(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old_out

    def test_add_success(self):
        rc, out = self._add()
        self.assertEqual(rc, 0)
        self.assertIn("✓", out)
        row = self.db.execute(
            "SELECT id, subject_id, predicate, object_id, source_seq FROM relations"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["subject_id"], 1)
        self.assertEqual(row["predicate"], "knows")
        self.assertEqual(row["object_id"], 2)
        self.assertIsNone(row["source_seq"])

    def test_add_with_source_seq(self):
        # Create an entry first so the FK is valid
        self.db.execute(
            "INSERT INTO entries(type, content, sha256) VALUES('tip', 'test', 'abc123')"
        )
        self.db.commit()
        rc, out = self._add(source_seq=1)
        self.assertEqual(rc, 0)
        row = self.db.execute("SELECT source_seq FROM relations WHERE predicate='knows'").fetchone()
        self.assertEqual(row["source_seq"], 1)

    def test_add_missing_subject(self):
        rc, out = self._add(subject_id=999)
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)
        self.assertIn("999", out)

    def test_add_missing_object(self):
        rc, out = self._add(object_id=999)
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)
        self.assertIn("999", out)

    def test_add_empty_predicate(self):
        rc, out = self._add(predicate="")
        self.assertEqual(rc, 1)
        self.assertIn("✗", out)

    def test_add_self_reference(self):
        """Relation where subject equals object is allowed."""
        rc, out = self._add(subject_id=1, object_id=1, predicate="self_ref")
        self.assertEqual(rc, 0)
        row = self.db.execute(
            "SELECT subject_id, object_id FROM relations WHERE predicate='self_ref'"
        ).fetchone()
        self.assertEqual(row["subject_id"], 1)
        self.assertEqual(row["object_id"], 1)

    def test_add_multiple_relations(self):
        for i, pred in enumerate(["knows", "uses", "trusts"]):
            self._add(predicate=pred)
        count = self.db.execute("SELECT count(*) FROM relations").fetchone()[0]
        self.assertEqual(count, 3)


class TestRelationList(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="rellist_test_")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def setUp(self):
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)
        self.db = mem.init_db()
        self.db.execute("INSERT INTO entities(id, name, type) VALUES(1, 'Alice', 'person')")
        self.db.execute("INSERT INTO entities(id, name, type) VALUES(2, 'Bob', 'person')")
        self.db.commit()

    def tearDown(self):
        self.db.close()
        if os.path.exists(mem.DB_PATH):
            os.remove(mem.DB_PATH)

    def _list(self):
        args = Namespace()
        from io import StringIO
        old_out = sys.stdout; sys.stdout = StringIO()
        try:
            rc = mem.cmd_relation_list(args)
            return rc, sys.stdout.getvalue()
        finally:
            sys.stdout = old_out

    def test_list_empty(self):
        rc, out = self._list()
        self.assertEqual(rc, 0)
        self.assertIn("暂无", out)

    def test_list_with_relations(self):
        self.db.execute(
            "INSERT INTO relations(subject_id, predicate, object_id) VALUES(1, 'knows', 2)"
        )
        self.db.commit()
        rc, out = self._list()
        self.assertEqual(rc, 0)
        self.assertIn("Alice", out)
        self.assertIn("knows", out)
        self.assertIn("Bob", out)


class TestParserDispatch(unittest.TestCase):
    """Verify entity/belief/relation are properly registered."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="parser_test_")
        mem.MEMORY_DIR = self.test_dir
        mem.DB_PATH = os.path.join(self.test_dir, "memory.db")
        mem.CONFIG_PATH = os.path.join(self.test_dir, "config.toml")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_entity_in_dispatch(self):
        self.assertIn("entity", mem.COMMAND_DISPATCH)
        self.assertIs(mem.COMMAND_DISPATCH["entity"], mem.cmd_entity)

    def test_belief_in_dispatch(self):
        self.assertIn("belief", mem.COMMAND_DISPATCH)
        self.assertIs(mem.COMMAND_DISPATCH["belief"], mem.cmd_belief)

    def test_relation_in_dispatch(self):
        self.assertIn("relation", mem.COMMAND_DISPATCH)
        self.assertIs(mem.COMMAND_DISPATCH["relation"], mem.cmd_relation)

    def test_entity_add_parses(self):
        parser = mem.build_parser()
        args = parser.parse_args(["entity", "add", "--name", "foo", "--type", "bar"])
        self.assertEqual(args.command, "entity")
        self.assertEqual(args.entity_cmd, "add")
        self.assertEqual(args.name, "foo")
        self.assertEqual(args.type, "bar")
        self.assertEqual(args.values, "[]")

    def test_entity_list_parses(self):
        parser = mem.build_parser()
        args = parser.parse_args(["entity", "list"])
        self.assertEqual(args.entity_cmd, "list")

    def test_belief_add_parses(self):
        parser = mem.build_parser()
        args = parser.parse_args([
            "belief", "add", "--content", "test", "--source-seqs", "[1]", "--confidence", "0.8"
        ])
        self.assertEqual(args.content, "test")
        self.assertEqual(args.source_seqs, "[1]")
        self.assertEqual(args.confidence, 0.8)

    def test_relation_add_parses(self):
        parser = mem.build_parser()
        args = parser.parse_args([
            "relation", "add", "--subject-id", "1", "--predicate", "knows",
            "--object-id", "2", "--source-seq", "5"
        ])
        self.assertEqual(args.subject_id, 1)
        self.assertEqual(args.predicate, "knows")
        self.assertEqual(args.object_id, 2)
        self.assertEqual(args.source_seq, 5)


if __name__ == "__main__":
    unittest.main()
