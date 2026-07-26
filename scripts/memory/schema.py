"""Database schema and initialization for Codex Memory."""

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
PRAGMA user_version=1;

CREATE TABLE IF NOT EXISTS entries (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    created          TEXT NOT NULL DEFAULT (datetime('now')),
    type             TEXT NOT NULL,
    content          TEXT NOT NULL,
    topics           TEXT DEFAULT '[]',
    sha256           TEXT NOT NULL,
    deleted          INTEGER NOT NULL DEFAULT 0,
    consolidated_seq INTEGER DEFAULT NULL,
    correction_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_entries_type
    ON entries(type, deleted);
CREATE INDEX IF NOT EXISTS idx_entries_created
    ON entries(created);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_sha256
    ON entries(sha256) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_entries_deleted
    ON entries(deleted, consolidated_seq);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    content, topics, tokenize='unicode61',
    content='entries', content_rowid='seq'
);




CREATE TABLE IF NOT EXISTS entries_vec (
    seq    INTEGER PRIMARY KEY,
    vector BLOB NOT NULL,
    model  TEXT NOT NULL,
    FOREIGN KEY (seq) REFERENCES entries(seq) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS system (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated TEXT DEFAULT (datetime('now'))
);


CREATE TABLE IF NOT EXISTS entities (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    type     TEXT NOT NULL,
    entity_values TEXT NOT NULL DEFAULT '[]',
    created  TEXT DEFAULT (datetime('now')),
    updated  TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_unique ON entities(name, type);
CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities
BEGIN UPDATE entities SET updated = datetime('now') WHERE id = new.id; END;

CREATE TABLE IF NOT EXISTS relations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    predicate  TEXT NOT NULL,
    object_id  INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source_seq INTEGER REFERENCES entries(seq) ON DELETE SET NULL,
    created    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_relations_subject_id ON relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_relations_object_id ON relations(object_id);

CREATE TABLE IF NOT EXISTS beliefs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT NOT NULL,
    source_seqs  TEXT NOT NULL DEFAULT '[]',
    confidence   REAL DEFAULT 0.5,
    previous_id  INTEGER REFERENCES beliefs(id),
    evolve_seq   INTEGER NOT NULL,
    created      TEXT DEFAULT (datetime('now'))
);
"""
