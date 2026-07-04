"""Task 1: Schema + init_db 单元测试"""

import sys, os, sqlite3, tempfile, shutil, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main as mem


class TestInitDB(unittest.TestCase):
    """Test schema creation and init_db()."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="schema_test_")

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

    def test_creates_db_file(self):
        self.assertTrue(os.path.exists(mem.DB_PATH))

    def test_tables_exist(self):
        names = [r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()]
        for t in ["entries", "entries_fts", "entries_vec", "system"]:
            self.assertIn(t, names)

    def test_triggers_exist(self):
        names = [r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()]
        # FTS5 triggers removed in v3; Python manages FTS5 sync via _sync_fts
        # Only entities_au trigger remains
        for t in ["entries_ai", "entries_ad", "entries_au"]:
            self.assertNotIn(t, names)

    def test_indexes_exist(self):
        names = [r["name"] for r in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_auto%' ORDER BY name"
        ).fetchall()]
        for idx in ["idx_entries_type", "idx_entries_created",
                     "idx_entries_sha256", "idx_entries_deleted"]:
            self.assertIn(idx, names)

    def test_system_seeds(self):
        rows = {r["key"]: r["value"] for r in self.db.execute(
            "SELECT key, value FROM system ORDER BY key"
        ).fetchall()}
        for k, v in [("evolve_seq", "0"), ("schema_version", "1"), ("total_adds", "0"),
                     ("total_corrections", "0"), ("total_evolves", "0")]:
            self.assertEqual(rows.get(k), v)

    def test_idempotent(self):
        mem.init_db().close()
        mem.init_db().close()
        for t in ["entries", "entries_fts", "entries_vec", "system"]:
            self.assertTrue(self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,)
            ).fetchone())

    def test_entries_schema(self):
        cols = [c["name"] for c in self.db.execute("PRAGMA table_info(entries)").fetchall()]
        for c in ["seq", "created", "type", "content", "topics", "sha256",
                    "deleted", "consolidated_seq", "correction_count"]:
            self.assertIn(c, cols)

    def test_correction_count_default(self):
        self.db.execute("INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)",
                        ("workflow", "t", "[]", "h1"))
        self.assertEqual(self.db.execute(
            "SELECT correction_count FROM entries WHERE sha256='h1'"
        ).fetchone()[0], 0)

    def test_wal_mode(self):
        self.assertEqual(self.db.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_fk_cascade_runtime(self):
        self.db.execute("INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)",
                        ("workflow", "t", "[]", "fk1"))
        s = self.db.execute("SELECT seq FROM entries WHERE sha256='fk1'").fetchone()["seq"]
        self.db.execute("INSERT INTO entries_vec(seq,vector,model) VALUES(?,?,?)",
                        (s, bytes(16), "m"))
        self.db.execute("DELETE FROM entries WHERE seq=?", (s,))
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM entries_vec WHERE seq=?", (s,)
        ).fetchone()[0], 0)

    def test_fts_trigger_sync(self):
        # FTS5 triggers removed in v3 — Python manages FTS5 sync via _sync_fts.
        # Direct INSERT no longer auto-syncs to FTS5.
        self.db.execute(
            "INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)",
            ("workflow", "hello world", "[]", "ft1"))
        hit = self.db.execute(
            "SELECT rowid FROM entries_fts WHERE entries_fts MATCH 'hello'"
        ).fetchone()
        self.assertIsNone(hit)

    def test_entries_vec_fk_defined(self):
        info = self.db.execute("PRAGMA foreign_key_list(entries_vec)").fetchall()
        self.assertTrue(len(info) > 0 and info[0]["on_delete"] == "CASCADE")



class TestMigrations(unittest.TestCase):
    """Test schema migration framework."""

    def test_user_version(self):
        """Fresh database starts at user_version >= 2."""
        import sqlite3, os, tempfile
        td = tempfile.mkdtemp()
        mem.MEMORY_DIR = td
        mem.DB_PATH = os.path.join(td, "m.db")
        db = mem.init_db()
        ver = db.execute("PRAGMA user_version").fetchone()[0]
        self.assertGreaterEqual(ver, 2)
        db.close()
        shutil.rmtree(td, ignore_errors=True)

    def test_migration_v1_to_v2(self):
        """Migration from v1 adds llm_processed_at and sets version."""
        import sqlite3, os, tempfile
        td = tempfile.mkdtemp()
        path = os.path.join(td, "migrate.db")
        db = sqlite3.connect(path)
        db.row_factory = sqlite3.Row
        db.executescript(mem.SCHEMA_SQL)
        db.execute("PRAGMA user_version = 1")
        cols = [r["name"] for r in db.execute("PRAGMA table_info(entries)")]
        self.assertNotIn("llm_processed_at", cols)
        mem._run_migrations(db)
        cols = [r["name"] for r in db.execute("PRAGMA table_info(entries)")]
        self.assertIn("llm_processed_at", cols)
        ver = db.execute("PRAGMA user_version").fetchone()[0]
        self.assertGreaterEqual(ver, 2)
        db.close()
        shutil.rmtree(td, ignore_errors=True)

if __name__ == "__main__":
    unittest.main()
