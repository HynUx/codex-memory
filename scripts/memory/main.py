#!/usr/bin/env python3
"""Codex 记忆系统 — CLI 入口

Usage:
    python3 main.py <command> [options]

Commands:
    add       Record a new learning entry
    search    Search existing memories
    list      Browse memories
    delete    Soft-delete a memory
    update    Update a memory entry
    evolve    Consolidate knowledge into project-context.md
    load      Load memory context for session start
    export    Export to Obsidian-compatible markdown
    status    Show system health dashboard
    migrate   Import from legacy learnings.jsonl
"""

import argparse
import fcntl
import hashlib
import json
import shutil
import os
import sqlite3
import sys
import time
import re
import embed
import seg

MEMORY_DIR = os.path.expanduser("~/.codex/memory")
DB_PATH = os.path.join(MEMORY_DIR, "memory.db")
LOCK_PATH = os.path.join(MEMORY_DIR, ".lock")
CONFIG_PATH = os.path.join(MEMORY_DIR, "config.toml")

# Available LLM models for learner mode (from Codex model list)
# These are the models the Codex agent can use for memory analysis.
AVAILABLE_MODELS = {
    "deepseek-v4-flash": "DeepSeek V4 Flash (fast, economical, recommended)",
    "deepseek-v4-pro":   "DeepSeek V4 Pro (high quality, slower)",
    "qwen3.7-plus":      "Qwen 3.7 Plus (alternative)",
    "glm-5.2":           "GLM 5.2 (alternative)",
}

# Default model for learner analysis
DEFAULT_LEARNER_MODEL = "deepseek-v4-flash"

VALID_TYPES = frozenset({
    "preference",
    "architecture",
    "workflow",
    "bug",
    "tip",
})

# ---- Schema ----------------------------------------------------------------

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

# ---- Database ---------------------------------------------------------------

def _sync_fts(db, seq, content, topics):
    """Synchronize FTS5 index for a single entry.

    Does NOT manage transactions — caller must wrap in appropriate
    BEGIN/COMMIT to ensure atomicity with the primary write.
    """
    seg_content = seg.maybe_segment(content)
    db.execute(
        "INSERT OR REPLACE INTO entries_fts(rowid, content, topics) VALUES(?, ?, ?)",
        (seq, seg_content, topics),
    )


def _run_migrations(db):
    """Run schema migrations based on PRAGMA user_version.

    Each migration checks current version and applies incremental
    changes, then increments user_version.  All migrations are
    designed to be idempotent (safe to re-apply).
    """
    version = db.execute("PRAGMA user_version").fetchone()[0]

    if version < 2:
        try:
            db.execute(
                "ALTER TABLE entries ADD COLUMN llm_processed_at TEXT DEFAULT NULL"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
        db.execute("PRAGMA user_version = 2")

    if version < 3:
        # Remove legacy FTS5 triggers
        db.executescript("""
            DROP TRIGGER IF EXISTS entries_ai;
            DROP TRIGGER IF EXISTS entries_ad;
            DROP TRIGGER IF EXISTS entries_au;
        """)
        # Re-index all active entries
        rows = db.execute(
            "SELECT seq, content, topics FROM entries WHERE deleted=0"
        ).fetchall()
        for r in rows:
            try:
                _sync_fts(db, r["seq"],
                          seg.maybe_segment(r["content"]), r["topics"])
            except Exception:
                # Fallback: sync with raw content
                _sync_fts(db, r["seq"], r["content"], r["topics"])
        db.execute("PRAGMA user_version = 3")


def init_db():
    """Open or create memory.db, returning a database connection.

    Creates the memory directory and runs the schema if the database
    file does not exist yet. Caller is responsible for closing the
    connection.
    """
    os.makedirs(MEMORY_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA_SQL)
    _run_migrations(db)
    seeds = [
        ("schema_version", "1"),
        ("evolve_seq", "0"),
        ("total_adds", "0"),
        ("total_corrections", "0"),
        ("total_evolves", "0"),
    ]
    for key, value in seeds:
        db.execute(
            "INSERT OR IGNORE INTO system(key, value) VALUES(?, ?)",
            (key, value),
        )
    db.commit()
    return db


# ---- Config ----------------------------------------------------------------


def load_config():
    """Load config.toml, return dict with defaults for missing keys."""
    cfg = {
        "auto_evolve_enabled": True,
        "auto_evolve_threshold": 10,
        "suggest_threshold": 10,
        "learner_model": DEFAULT_LEARNER_MODEL,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")  # I1: strip outer quotes first
                    if val.lower() in ("true", "false"):
                        cfg[key] = val.lower() == "true"
                    elif val.isdigit():
                        cfg[key] = int(val)
                    elif key in cfg:
                        # F1: don't overwrite defaults with invalid values
                        print(f"\u26a0 \u914d\u7f6e\u503c\u65e0\u6548: {key}={val}\uff0c\u4f7f\u7528\u9ed8\u8ba4\u503c", file=sys.stderr)
        except (OSError, ValueError) as e:
            # I2: user can see config read failures
            print(f"\u26a0 \u8bfb\u53d6\u914d\u7f6e\u5931\u8d25: {e}\uff0c\u4f7f\u7528\u9ed8\u8ba4\u503c", file=sys.stderr)
    return cfg


# ---- Commands ---------------------------------------------------------------


def cmd_add(args):
    """Record a new learning entry."""
    db = init_db()

    if args.type not in VALID_TYPES:
        valid_list = ", ".join(sorted(VALID_TYPES))
        print(f"✗ 无效类型: {args.type}，有效值: {valid_list}")
        db.close()
        return 1

    content = (args.content or "").strip()
    if not content:
        print("✗ 内容不能为空")
        db.close()
        return 1

    topics_raw = args.topics or "[]"
    sha256 = hashlib.sha256(
        (content + args.type + topics_raw).encode("utf-8")
    ).hexdigest()

    existing = db.execute(
        "SELECT seq FROM entries WHERE sha256 = ? AND deleted = 0",
        (sha256,),
    ).fetchone()
    if existing is not None:
        print(f"⏭ 已存在 (seq={existing['seq']})")
        db.close()
        return

    db.execute(
        "INSERT INTO entries(type, content, topics, sha256) VALUES (?, ?, ?, ?)",
        (args.type, content, topics_raw, sha256),
    )
    seq = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    _sync_fts(db, seq, content, topics_raw)
    db.execute("UPDATE system SET value = CAST(value AS INTEGER) + 1 WHERE key = 'total_adds'")
    db.commit()

    print(f"✓ 已记录 (seq={seq})")

    # Auto-evolve trigger
    if not getattr(args, 'no_evolve', False):
        cfg = load_config()
        if cfg.get("auto_evolve_enabled", True):
            unmerged = db.execute(
                "SELECT count(*) FROM entries WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count>0)"
            ).fetchone()[0]
            threshold = cfg.get("auto_evolve_threshold", 10)
            if unmerged >= threshold:
                db.close()
                print("触发自动进化...")
                lf = open(LOCK_PATH, 'w')
                try:
                    fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(lf, fcntl.LOCK_UN)
                except IOError:
                    print("自动进化跳过（其他进程正在处理）")
                    return 0
                finally:
                    lf.close()
                cmd_evolve(None)
                return 0

    db.close()
    return 0

def cmd_search(args):
    """Search memories via FTS5 with LIKE fallback."""
    db = init_db()
    kw = args.keywords
    fts_kw = seg.maybe_segment(kw)
    limit = getattr(args, "limit", 5)
    offset = getattr(args, "offset", 0)

    rows = db.execute(
        """SELECT e.seq, e.type, e.content, e.topics FROM entries_fts f
           JOIN entries e ON f.rowid = e.seq
           WHERE entries_fts MATCH ? AND e.deleted=0
           ORDER BY rank LIMIT ? OFFSET ?""",
        (fts_kw, limit, offset),
    ).fetchall()

    if not rows:
        like = "%%%s%%" % kw
        rows = db.execute(
            "SELECT seq, type, content, topics FROM entries WHERE content LIKE ? AND deleted=0 LIMIT ? OFFSET ?",
            (like, limit, offset),
        ).fetchall()

    # Vector search fallback (when FTS5 + LIKE miss)
    if not rows and embed.is_available():
        vec_entries = db.execute(
            "SELECT e.seq, v.vector FROM entries_vec v JOIN entries e ON v.seq = e.seq WHERE e.deleted=0"
        ).fetchall()
        if vec_entries:
            results = embed.search(kw, [(r["seq"], r["vector"]) for r in vec_entries], limit)
            if results:
                seqs = [r[1] for r in results]
                ph = ",".join("?" * len(seqs))
                rows = db.execute(
                    "SELECT seq, type, content, topics FROM entries WHERE seq IN (%s)" % ph,
                    seqs,
                ).fetchall()

    if not rows:
        print("未找到相关记忆")
        db.close()
        return 0

    print("相关记忆（共 %d 条）：" % len(rows))
    for seq, typ, content, topics in rows:
        print("  [seq:%d] %s | %s | %.60s..." % (seq, typ, topics, content))
    db.close()
    return 0


def cmd_list(args):
    """Browse all memories without keywords."""
    db = init_db()
    limit = getattr(args, "limit", 10)
    unprocessed = getattr(args, "unprocessed", False)
    if unprocessed:
        rows = db.execute(
            "SELECT seq, type, content, topics FROM entries WHERE deleted=0 AND llm_processed_at IS NULL AND (consolidated_seq IS NULL OR correction_count>0) ORDER BY seq LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT seq, type, content, topics FROM entries WHERE deleted=0 ORDER BY seq DESC LIMIT ?",
            (limit,),
        ).fetchall()

    if not rows:
        print("暂无记忆")
        db.close()
        return 0

    print("记忆列表（共 %d 条）：" % len(rows))
    for seq, typ, content, topics in rows:
        print("  [seq:%d] %s | %s | %.60s..." % (seq, typ, topics, content))
    db.close()
    return 0



def cmd_delete(args):
    """Soft-delete a memory entry by seq."""
    db = init_db()
    row = db.execute(
        "SELECT seq, consolidated_seq FROM entries WHERE seq=? AND deleted=0",
        (args.seq,),
    ).fetchone()
    if not row:
        print("✗ 未找到")
        db.close()
        return 1
    seq, cs = row["seq"], row["consolidated_seq"]
    db.execute("UPDATE entries SET deleted=1 WHERE seq=?", (seq,))
    db.execute("DELETE FROM entries_fts WHERE rowid = ?", (seq,))
    if cs is not None:
        db.execute("UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?", (seq,))
        db.execute(
            "UPDATE system SET value = CAST(value AS INTEGER) + 1 WHERE key='total_corrections'"
        )
    db.commit()
    print("\u2713 \u5df2\u5220\u9664 (seq=%d)" % seq)
    db.close()
    return 0


def cmd_update(args):
    """Update a memory entry by seq. Supports partial field updates."""
    db = init_db()
    row = db.execute(
        "SELECT seq, consolidated_seq, type, content, topics FROM entries WHERE seq=? AND deleted=0",
        (args.seq,),
    ).fetchone()
    if not row:
        print("✗ 未找到")
        db.close()
        return 1
    new_type = args.type if args.type else row["type"]
    new_content = args.content if args.content else row["content"]
    new_topics = args.topics if args.topics else row["topics"]
    new_sha256 = hashlib.sha256((new_content + new_type + new_topics).encode("utf-8")).hexdigest()
    dup = db.execute(
        "SELECT seq FROM entries WHERE sha256=? AND deleted=0 AND seq!=?",
        (new_sha256, args.seq),
    ).fetchone()
    if dup:
        print("✗ 冲突: 已存在相同内容 (seq=%d)" % dup["seq"])
        db.close()
        return 1
    db.execute(
        "UPDATE entries SET type=?, content=?, topics=?, sha256=? WHERE seq=?",
        (new_type, new_content, new_topics, new_sha256, args.seq),
    )
    _sync_fts(db, args.seq, new_content, new_topics)
    if row["consolidated_seq"] is not None:
        db.execute(
            "UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?",
            (args.seq,),
        )
        db.execute(
            "UPDATE system SET value = CAST(value AS INTEGER) + 1 WHERE key='total_corrections'"
        )
    db.commit()
    print("\u2713 \u5df2\u66f4\u65b0 (seq=%d)" % args.seq)
    db.close()
    return 0


_lock_fd = None


def acquire_lock():
    """Acquire an exclusive file lock for evolve."""
    global _lock_fd
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    _lock_fd = open(LOCK_PATH, 'w')
    fcntl.flock(_lock_fd, fcntl.LOCK_EX)


def release_lock():
    """Release the file lock."""
    global _lock_fd
    if _lock_fd is not None:
        fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        _lock_fd.close()
        _lock_fd = None



def _vec_rebuild(db):
    """Rebuild vector index for active entries. Caller must ensure embed.is_available()."""
    rows = db.execute(
        "SELECT seq, content, type, topics FROM entries WHERE deleted=0"
    ).fetchall()
    if not rows:
        return
    db.execute("BEGIN")
    count = 0
    failed = 0
    for i, row in enumerate(rows):
        text = "%s: %s %s" % (row["type"], row["content"], row["topics"])
        try:
            vec = embed.embed(text)
            if not vec.any():
                failed += 1
                continue  # skip zero vectors (embed failure)
            db.execute(
                "INSERT OR REPLACE INTO entries_vec(seq, vector, model) VALUES(?, ?, ?)",
                (row["seq"], vec.tobytes(), "bge-small-zh-v1.5"),
            )
            count += 1
            if count > 0 and count % 100 == 0:
                db.commit()
                db.execute("BEGIN")
        except Exception:
            failed += 1
            continue  # skip failed entries
    db.commit()
    if count > 0:
        print(f"\u5411\u91cf\u7d22\u5f15\u5df2\u66f4\u65b0: {count} \u6761")
def cmd_evolve(args):
    """Consolidate unmerged entries into project-context.md.

    Writes ALL active entries to project-context.md (not just unmerged
    ones), marks newly unmerged entries as consolidated, and prunes old
    backups beyond the retention limit.
    """
    acquire_lock()
    try:
        db = init_db()
        V = int(db.execute(
            "SELECT value FROM system WHERE key='evolve_seq'"
        ).fetchone()["value"]) + 1

        # All active entries for output
        all_active = db.execute(
            "SELECT seq, type, content, topics, correction_count FROM entries "
            "WHERE deleted=0 ORDER BY seq"
        ).fetchall()

        # Deleted entries with pending corrections
        deleted_with_cc = db.execute(
            "SELECT seq, type, content, topics, correction_count FROM entries "
            "WHERE deleted=1 AND correction_count > 0 ORDER BY seq"
        ).fetchall()

        # Unmerged entries that need consolidated_seq update
        unmerged = db.execute(
            "SELECT seq, correction_count FROM entries "
            "WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count > 0)"
        ).fetchall()

        if not all_active and not deleted_with_cc:
            print("\u6ca1\u6709\u9700\u8981\u8fdb\u5316\u7684\u8bb0\u5f55")
            db.close()
            release_lock()
            return 0

        pc_path = os.path.join(MEMORY_DIR, "project-context.md")
        backup_dir = os.path.join(MEMORY_DIR, ".backup")
        os.makedirs(backup_dir, exist_ok=True)
        if os.path.exists(pc_path):
            shutil.copy2(pc_path, os.path.join(backup_dir, "v%d.bak" % (V - 1)))

        # Write ALL active entries (preserving consolidated ones)
        out = "<!-- evolve_seq: %d -->\n\n# \u9879\u76ee\u4e0a\u4e0b\u6587\n\n" % V
        for e in all_active:
            tag = " [user_correction]" if e["correction_count"] > 0 else ""
            out += "- seq=%d [%s%s]: %s\n" % (e["seq"], e["type"], tag, e["content"])

        if deleted_with_cc:
            out += "\n## \u5df2\u5220\u9664\n\n"
            for e in deleted_with_cc:
                out += "- seq=%d: ~~%s~~\n" % (e["seq"], e["content"])

        tmp = pc_path + ".tmp"
        with open(tmp, "w") as f:
            f.write(out)

        # Only mark newly unmerged entries as consolidated
        cc_map = {r["seq"]: r["correction_count"] for r in unmerged}
        db.execute("BEGIN")
        for seq, cc in cc_map.items():
            db.execute(
                "UPDATE entries SET consolidated_seq=?, correction_count=0 "
                "WHERE seq=? AND correction_count=?",
                (V, seq, cc),
            )
        for e in deleted_with_cc:
            db.execute(
                "UPDATE entries SET correction_count=0 WHERE seq=?",
                (e["seq"],),
            )
        db.execute(
            "INSERT OR REPLACE INTO system(key, value, updated) "
            "VALUES('evolve_seq', ?, datetime('now'))",
            (str(V),),
        )
        db.execute(
            "UPDATE system SET value = CAST(value AS INTEGER) + 1 WHERE key='total_evolves'"
        )
        db.commit()
        os.rename(tmp, pc_path)
        print("\u2713 \u8fdb\u5316\u5b8c\u6210 (V=%d)" % V)

        # Auto-sync vector index after evolve
        if embed.is_available():
            unindexed = db.execute(
                "SELECT count(*) FROM entries e LEFT JOIN entries_vec v "
                "ON e.seq=v.seq WHERE e.deleted=0 AND v.seq IS NULL"
            ).fetchone()[0]
            if unindexed > 0:
                print("\u5411\u91cf\u7d22\u5f15\u540c\u6b65\u4e2d...")
                _vec_rebuild(db)

        # Backup retention: keep last 10 v{N}.bak files
        if os.path.exists(backup_dir):
            bak_files = []
            for fn in os.listdir(backup_dir):
                m = re.match(r'v(\d+)\.bak', fn)
                if m:
                    bak_files.append((int(m.group(1)), fn))
            bak_files.sort(key=lambda x: -x[0])  # newest first
            for ver, fn in bak_files[10:]:
                os.remove(os.path.join(backup_dir, fn))
                print("  \u6e05\u7406\u65e7\u5907\u4efd: %s" % fn)

        db.close()
    finally:
        release_lock()
    return 0





def cmd_load(args):
    """Load memory context for session start."""
    db = init_db()
    output = ""

    pf = os.path.join(MEMORY_DIR, "profile.md")
    if os.path.exists(pf):
        with open(pf) as f:
            output += f.read() + "\n"

    pc = os.path.join(MEMORY_DIR, "project-context.md")
    if os.path.exists(pc):
        with open(pc) as f:
            text = f.read()
        ev = db.execute("SELECT value FROM system WHERE key='evolve_seq'").fetchone()["value"]
        m = re.search(r'<!-- evolve_seq:\s*(\d+)\s*-->', text)
        if m and int(m.group(1)) < int(ev):
            print("\u26a0\ufe0f project-context.md \u5df2\u8fc7\u671f\uff0c\u5efa\u8bae\u8fd0\u884c memory evolve")
        output += text + "\n"

    recent = db.execute(
        "SELECT seq, type, content, topics FROM entries WHERE deleted=0 ORDER BY seq DESC LIMIT ?",
        (getattr(args, "limit", 10),),
    ).fetchall()
    if recent:
        output += "## \u6700\u8fd1\u5b66\u4e60\n"
        for row in recent:
            output += "- [seq:%d] %s | %.80s...\n" % (row["seq"], row["type"], row["content"])

    unmerged = db.execute(
        "SELECT count(*) FROM entries WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count>0)"
    ).fetchone()[0]
    cfg_sug = load_config().get("suggest_threshold", 10)
    if unmerged >= cfg_sug:
        print("\u26a0\ufe0f %d \u6761\u672a\u5408\u5e76\uff0c\u8fd0\u884c memory evolve \u66f4\u65b0" % unmerged)

    if len(output) > 12000:
        output = output[:12000] + "\n...\uff08\u622a\u65ad\uff09"

    print(output)
    db.close()
    return 0


def cmd_export(args):
    """Export memories to Obsidian-compatible markdown files."""
    db = init_db()
    export_dir = getattr(args, "dir", os.path.join(MEMORY_DIR, "export"))
    if os.path.exists(export_dir):
        shutil.rmtree(export_dir)
    os.makedirs(export_dir)

    rows = db.execute(
        "SELECT seq, created, type, content, topics FROM entries WHERE deleted=0 ORDER BY seq"
    ).fetchall()

    for row in rows:
        seq, typ, text = row["seq"], row["type"], row["content"]
        created, topics = row["created"], row["topics"]
        safe = typ.replace(" ", "-").replace("/", "_")
        fn = "seq-%04d-%s.md" % (seq, safe)
        tags = []
        if topics and topics != "[]":
            tags = [t.strip().strip('"') for t in topics.strip("[]").split(",")]
        tag_str = ", ".join(t for t in tags)

        md = """---
seq: %d
type: %s
topics: %s
created: %s
tags: [%s]
---

# %.60s

%s

---
*Source: memory.db | \u5bfc\u51fa: %s*
""" % (seq, typ, topics, created, tag_str, text, text, time.strftime("%Y-%m-%d %H:%M"))

        with open(os.path.join(export_dir, fn), "w") as f:
            f.write(md)

    with open(os.path.join(export_dir, "_index.md"), "w") as f:
        f.write("""# \u8bb0\u5fc6\u4eea\u8868\u76d8

\u5bfc\u51fa\u65f6\u95f4: %s

\u603b\u8bb0\u5f55: %d

\u6587\u4ef6\u6570: %d
""" % (time.strftime("%Y-%m-%d %H:%M"), len(rows), len(rows)))

    print("\u2713 \u5df2\u5bfc\u51fa %d \u6761\u5230 %s" % (len(rows), export_dir))
    db.close()
    return 0


def cmd_status(args):
    """Show system health dashboard with DB size and backup info."""
    db = init_db()

    total = db.execute("SELECT count(*) FROM entries").fetchone()[0]
    active = db.execute("SELECT count(*) FROM entries WHERE deleted=0").fetchone()[0]
    deleted = db.execute("SELECT count(*) FROM entries WHERE deleted=1").fetchone()[0]
    unmerged = db.execute(
        "SELECT count(*) FROM entries WHERE deleted=0 "
        "AND (consolidated_seq IS NULL OR correction_count>0)"
    ).fetchone()[0]

    es = db.execute("SELECT value FROM system WHERE key='evolve_seq'").fetchone()["value"]
    ta = db.execute("SELECT value FROM system WHERE key='total_adds'").fetchone()["value"]
    tc = db.execute("SELECT value FROM system WHERE key='total_corrections'").fetchone()["value"]
    te = db.execute("SELECT value FROM system WHERE key='total_evolves'").fetchone()["value"]

    # DB file size (human-readable)
    try:
        size_bytes = os.path.getsize(DB_PATH)
        if size_bytes < 1024:
            size_str = "%d B" % size_bytes
        elif size_bytes < 1024 * 1024:
            size_str = "%.1f KB" % (size_bytes / 1024)
        else:
            size_str = "%.1f MB" % (size_bytes / (1024 * 1024))
    except OSError:
        size_str = "?"

    # Count only v{N}.bak backup files
    bd = os.path.join(MEMORY_DIR, ".backup")
    backups = 0
    if os.path.exists(bd):
        for fn in os.listdir(bd):
            if re.match(r'v(\d+)\.bak', fn):
                backups += 1
    vc = db.execute("SELECT count(*) FROM entries_vec").fetchone()[0]

    print("\U0001f4ca \u8bb0\u5fc6\u7cfb\u7edf\u72b6\u6001")
    print("  \u603b\u8bb0\u5f55: %d | \u6709\u6548: %d | \u672a\u5408\u5e76: %d | \u5df2\u5220\u9664: %d | \u5927\u5c0f: %s" % (
        total, active, unmerged, deleted, size_str))
    print("\U0001f4c8 \u8fdb\u5316\u8ffd\u8e2a")
    print("  \u7248\u672c: v%s | \u5386\u53f2\u7248\u672c: %d \u4e2a" % (es, backups))
    print("  \u7d2f\u8ba1: %s adds / %s corrections / %s evolves" % (ta, tc, te))
    print("\U0001f50d \u641c\u7d22")
    print("  FTS5: \u2705 | \u5411\u91cf: %s (%d/%d \u5df2\u7d22\u5f15)" % (
        "\u2705" if vc > 0 else "\u274c (\u672a\u542f\u7528)", vc, active))

    db.close()
    return 0



def cmd_vec(args):
    """Manage vector embeddings (BGE-small-zh via sentence-transformers)."""
    db = init_db()
    sub = getattr(args, "vec_cmd", "status")
    if sub == "status":
        cnt = db.execute("SELECT count(*) FROM entries_vec").fetchone()[0]
        total = db.execute("SELECT count(*) FROM entries WHERE deleted=0").fetchone()[0]
        avail = embed.is_available()
        if avail:
            print("向量状态: \u2705 \u53ef\u7528")
        else:
            print("向量状态: \u274c \u672a\u542f\u7528\uff08\u9700\u5b89\u88c5: pip install sentence-transformers\uff09")
        print("\u5df2\u7d22\u5f15: %d/%d \u6761" % (cnt, total))
    elif sub == "enable":
        if not embed.is_available():
            print("\u2717 \u9700\u8981\u5b89\u88c5 sentence-transformers")
            print("  pip install sentence-transformers")
            db.close()
            return 1
        embed.download_model()
        rows = db.execute("SELECT seq, content, type, topics FROM entries WHERE deleted=0").fetchall()
        for row in rows:
            text = "%s: %s %s" % (row["type"], row["content"], row["topics"])
            vec = embed.embed(text)
            db.execute(
                "INSERT OR REPLACE INTO entries_vec(seq, vector, model) VALUES(?, ?, ?)",
                (row["seq"], vec.tobytes(), "bge-small-zh-v1.5"),
            )
        db.commit()
        print("\u2713 \u5df2\u7d22\u5f15 %d \u6761" % len(rows))
    elif sub == "rebuild":
        db.execute("DELETE FROM entries_vec")
        db.commit()
        if not embed.is_available():
            print("\u2717 \u9700\u8981\u5b89\u88c5 sentence-transformers")
            db.close()
            return 1
        embed.download_model()
        rows = db.execute("SELECT seq, content, type, topics FROM entries WHERE deleted=0").fetchall()
        for row in rows:
            text = "%s: %s %s" % (row["type"], row["content"], row["topics"])
            vec = embed.embed(text)
            db.execute(
                "INSERT OR REPLACE INTO entries_vec(seq, vector, model) VALUES(?, ?, ?)",
                (row["seq"], vec.tobytes(), "bge-small-zh-v1.5"),
            )
        db.commit()
        print("\u2713 \u5df2\u91cd\u5efa\u7d22\u5f15: %d \u6761" % len(rows))
    db.close()
    return 0

def cmd_migrate(args):
    """Import from legacy learnings.jsonl."""
    jsonl_path = os.path.join(MEMORY_DIR, "learnings.jsonl")
    if not os.path.exists(jsonl_path):
        print("✗ 未找到 learnings.jsonl")
        return 1
    db = init_db()
    count = 0
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            typ = rec.get("type", "tip")
            if isinstance(typ, str) and typ.startswith("_"):
                continue
            content = rec.get("content", "")
            topics_raw = rec.get("topics", "")
            if isinstance(topics_raw, str):
                topics = json.dumps(topics_raw.split(","))
            else:
                topics = "[]"
            sha256 = hashlib.sha256(
                (content + typ + topics).encode("utf-8")
            ).hexdigest()
            dup = db.execute(
                "SELECT seq FROM entries WHERE sha256=? AND deleted=0", (sha256,)
            ).fetchone()
            if dup:
                continue
            db.execute(
                "INSERT INTO entries(type, content, topics, sha256) VALUES (?, ?, ?, ?)",
                (typ, content, topics, sha256),
            )
            seq = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            _sync_fts(db, seq, content, topics)
            count += 1
    db.commit()
    print("\u2713 \u5df2\u8fc1\u79fb %d \u6761\u8bb0\u5f55" % count)
    db.close()
    return 0


def cmd_entity(args):
    """Dispatch entity subcommands."""
    sub = getattr(args, "entity_cmd", None)
    if sub == "add":
        return cmd_entity_add(args)
    elif sub == "list":
        return cmd_entity_list(args)
    else:
        print("✗ 未知实体子命令: %s" % sub)
        return 1


def cmd_belief(args):
    """Dispatch belief subcommands."""
    sub = getattr(args, "belief_cmd", None)
    if sub == "add":
        return cmd_belief_add(args)
    elif sub == "list":
        return cmd_belief_list(args)
    else:
        print("✗ 未知信念子命令: %s" % sub)
        return 1


def cmd_relation(args):
    """Dispatch relation subcommands."""
    sub = getattr(args, "relation_cmd", None)
    if sub == "add":
        return cmd_relation_add(args)
    elif sub == "list":
        return cmd_relation_list(args)
    else:
        print("✗ 未知关系子命令: %s" % sub)
        return 1


def cmd_entity_add(args):
    """Add a new entity."""
    db = init_db()
    name = (args.name or "").strip()
    if not name:
        print("✗ 名称不能为空")
        db.close()
        return 1
    etype = (args.type or "").strip()
    if not etype:
        print("✗ 类型不能为空")
        db.close()
        return 1
    values = getattr(args, "values", None) or "[]"
    try:
        db.execute(
            "INSERT INTO entities(name, type, entity_values) VALUES(?, ?, ?)",
            (name, etype, values),
        )
        db.commit()
        eid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        print(f"✓ 实体已创建 (id={eid})")
    except sqlite3.IntegrityError:
        existing = db.execute(
            "SELECT id FROM entities WHERE name=? AND type=?", (name, etype)
        ).fetchone()
        print(f"⏭ 已存在 (id={existing['id']})")
    db.close()
    return 0


def cmd_entity_list(args):
    """List all entities."""
    db = init_db()
    rows = db.execute(
        "SELECT id, name, type, entity_values, created, updated FROM entities ORDER BY id"
    ).fetchall()
    if not rows:
        print("暂无实体")
        db.close()
        return 0
    print("实体列表（共 %d 条）：" % len(rows))
    for row in rows:
        print("  [id:%d] %s (%s) | values=%s | created=%s" % (
            row["id"], row["name"], row["type"],
            row["entity_values"], row["created"],
        ))
    db.close()
    return 0


def cmd_belief_add(args):
    """Add a new belief."""
    db = init_db()
    content = (args.content or "").strip()
    if not content:
        print("✗ 内容不能为空")
        db.close()
        return 1
    source_seqs = getattr(args, "source_seqs", None) or "[]"
    confidence = getattr(args, "confidence", None)
    if confidence is None:
        confidence = 0.5
    if not (0.0 <= confidence <= 1.0):
        print("✗ 置信度必须在 0.0 ~ 1.0 之间")
        db.close()
        return 1
    evolve_seq = int(db.execute(
        "SELECT value FROM system WHERE key='evolve_seq'"
    ).fetchone()["value"])
    db.execute(
        "INSERT INTO beliefs(content, source_seqs, confidence, evolve_seq) VALUES(?, ?, ?, ?)",
        (content, source_seqs, confidence, evolve_seq),
    )
    db.commit()
    bid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(f"✓ 信念已记录 (id={bid})")
    db.close()
    return 0


def cmd_belief_list(args):
    """List all beliefs."""
    db = init_db()
    rows = db.execute(
        "SELECT id, content, source_seqs, confidence, evolve_seq, previous_id, created FROM beliefs ORDER BY id"
    ).fetchall()
    if not rows:
        print("暂无疑念")
        db.close()
        return 0
    print("信念列表（共 %d 条）：" % len(rows))
    for row in rows:
        prev = f" (prev={row['previous_id']})" if row["previous_id"] else ""
        print("  [id:%d] %.60s... | conf=%.2f | evolve=%d%s | %s" % (
            row["id"], row["content"], row["confidence"],
            row["evolve_seq"], prev, row["created"],
        ))
    db.close()
    return 0


def cmd_relation_add(args):
    """Add a new relation between entities."""
    db = init_db()
    sid = args.subject_id
    oid = args.object_id
    predicate = (args.predicate or "").strip()
    if not predicate:
        print("✗ 谓词不能为空")
        db.close()
        return 1
    subj = db.execute("SELECT id FROM entities WHERE id=?", (sid,)).fetchone()
    if not subj:
        print(f"✗ 主体实体不存在 (id={sid})")
        db.close()
        return 1
    obj = db.execute("SELECT id FROM entities WHERE id=?", (oid,)).fetchone()
    if not obj:
        print(f"✗ 客体实体不存在 (id={oid})")
        db.close()
        return 1
    source_seq = getattr(args, "source_seq", None)
    if source_seq is not None:
        entry_exists = db.execute(
            "SELECT seq FROM entries WHERE seq=?", (source_seq,)
        ).fetchone()
        if not entry_exists:
            print(f"⚠ 来源条目不存在 (seq={source_seq})，将 source_seq 设为 NULL")
            source_seq = None
    db.execute(
        "INSERT INTO relations(subject_id, predicate, object_id, source_seq) VALUES(?, ?, ?, ?)",
        (sid, predicate, oid, source_seq),
    )
    db.commit()
    rid = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    print(f"✓ 关系已创建 (id={rid})")
    db.close()
    return 0


def cmd_relation_list(args):
    """List all relations."""
    db = init_db()
    rows = db.execute(
        """SELECT r.id, s.name AS subj_name, r.predicate,
                  o.name AS obj_name, r.source_seq, r.created
           FROM relations r
           LEFT JOIN entities s ON r.subject_id = s.id
           LEFT JOIN entities o ON r.object_id = o.id
           ORDER BY r.id"""
    ).fetchall()
    if not rows:
        print("暂无关系")
        db.close()
        return 0
    print("关系列表（共 %d 条）：" % len(rows))
    for row in rows:
        src = f" [source: seq={row['source_seq']}]" if row["source_seq"] else ""
        print("  [id:%d] %s --[%s]--> %s%s | %s" % (
            row["id"], row["subj_name"] or "?",
            row["predicate"], row["obj_name"] or "?",
            src, row["created"],
        ))
    db.close()
    return 0






def build_parser():
    """Build and return the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(prog="memory")
    sub = parser.add_subparsers(dest="command")

    # add
    p = sub.add_parser("add", help="记录一条学习")
    p.add_argument(
        "--type", required=True,
        choices=sorted(VALID_TYPES),
        help="记录类型",
    )
    p.add_argument("--content", required=True, help="学习内容")
    p.add_argument("--topics", default="[]", help="标签，JSON 数组")
    p.add_argument(
        "--no-evolve", action="store_true",
        help="跳过自动 evolve 触发",
    )


    # search
    p = sub.add_parser("search", help="搜索记忆")
    p.add_argument("keywords", help="搜索关键词")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--type", help="按类型过滤")
    p.add_argument("--topic", help="按主题过滤")
    p.add_argument("--days", type=int, help="最近 N 天")

    # list
    p = sub.add_parser("list", help="浏览记忆")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--unprocessed", action="store_true",
                    help="仅列出未 LLM 处理的条目")
    # delete
    p = sub.add_parser("delete", help="软删除一条记忆")
    p.add_argument("seq", type=int, help="要删除的记录序号")

    # update
    p = sub.add_parser("update", help="更新一条记忆")
    p.add_argument("seq", type=int, help="要更新的记录序号")
    p.add_argument("--content", help="新内容")
    p.add_argument("--type", help="新类型")
    p.add_argument("--topics", help="新标签")

    # evolve
    p = sub.add_parser("evolve", help="合并记忆到 project-context.md")

    # load
    p = sub.add_parser("load", help="加载记忆上下文")
    p.add_argument("--limit", type=int, default=10)
    # export
    p = sub.add_parser("export", help="导出 Obsidian 兼容 Markdown")
    p.add_argument("--dir", help="导出目录")

    # status
    # review
    p = sub.add_parser("review", help="输出未 LLM 处理的条目用于分析")
    p.add_argument("review_cmd", nargs="?", default="list",
                    choices=["list", "mark"],
                    help="list=列出未处理条目, mark=标记已处理")
    p.add_argument("--limit", type=int, default=20,
                    help="列出条数上限")
    p.add_argument("--seq", type=int, help="要标记的 seq")


    # config
    p = sub.add_parser("config", help="配置系统")
    p.add_argument("config_cmd", nargs="?", default="show",
                    choices=["show", "set-model"],
                    help="配置操作")
    p.add_argument("--model", help="设置学习模型")

    # status
    p = sub.add_parser("status", help="系统状态仪表盘")

    # vec
    p = sub.add_parser("vec", help="向量索引管理")
    p.add_argument("vec_cmd", nargs="?", default="status",
                    choices=["enable", "rebuild", "status"])

    # migrate
    p = sub.add_parser("migrate", help="从 learnings.jsonl 导入")

    # entity
    p = sub.add_parser("entity", help="实体管理")
    e_sub = p.add_subparsers(dest="entity_cmd")
    ep = e_sub.add_parser("add", help="添加实体")
    ep.add_argument("--name", required=True, help="实体名称")
    ep.add_argument("--type", required=True, help="实体类型")
    ep.add_argument("--values", default="[]", help="实体值 JSON 数组")
    ep = e_sub.add_parser("list", help="列出所有实体")

    # belief
    p = sub.add_parser("belief", help="信念管理")
    b_sub = p.add_subparsers(dest="belief_cmd")
    bp = b_sub.add_parser("add", help="添加信念")
    bp.add_argument("--content", required=True, help="信念内容")
    bp.add_argument("--source-seqs", default="[]", help="来源条目序号 JSON 数组")
    bp.add_argument("--confidence", type=float, default=0.5, help="置信度 0.0~1.0")
    bp = b_sub.add_parser("list", help="列出所有信念")

    # relation
    p = sub.add_parser("relation", help="关系管理")
    r_sub = p.add_subparsers(dest="relation_cmd")
    rp = r_sub.add_parser("add", help="添加关系")
    rp.add_argument("--subject-id", type=int, required=True, help="主体实体 ID")
    rp.add_argument("--predicate", required=True, help="关系谓词")
    rp.add_argument("--object-id", type=int, required=True, help="客体实体 ID")
    rp.add_argument("--source-seq", type=int, help="来源条目序号")
    rp = r_sub.add_parser("list", help="列出所有关系")

    return parser



def cmd_config(args):
    """Configure memory system settings."""
    cfg_path = CONFIG_PATH
    sub = getattr(args, "config_cmd", "show")
    
    if sub == "show":
        print("\n当前配置:")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                print(f.read())
        else:
            print("  无配置文件（使用默认值）")
        print(f"\n可用模型:")
        for name, desc in AVAILABLE_MODELS.items():
            marker = " *" if name == load_config().get("learner_model", DEFAULT_LEARNER_MODEL) else "  "
            print(f"  {marker} {name}: {desc}")
        return 0
    
    if sub == "set-model":
        model = getattr(args, "model", None)
        if not model:
            print(f"请指定模型: --model <名称>")
            print(f"可用模型: {', '.join(AVAILABLE_MODELS.keys())}")
            return 1
        if model not in AVAILABLE_MODELS:
            print(f"无效模型: {model}")
            print(f"可用模型: {', '.join(AVAILABLE_MODELS.keys())}")
            return 1
        
        # Update learner_model in config.toml (preserve comments and other keys)
        updated_lines = []
        found = False
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                for line in f:
                    stripped = line.lstrip()
                    if stripped.startswith('learner_model') and '=' in stripped:
                        updated_lines.append(f'learner_model = {model}\n')
                        found = True
                    else:
                        updated_lines.append(line)
        if not found:
            updated_lines.append(f'learner_model = {model}\n')
        with open(cfg_path, 'w') as f:
            f.writelines(updated_lines)
        
        print(f"\u2713 learner_model \u5df2\u8bbe\u4e3a: {model}")
        return 0
    
    return 0


def cmd_review(args):
    """Output unprocessed entries for Codex agent to analyze with LLM."""
    db = init_db()
    cfg = load_config()
    model = cfg.get("learner_model", DEFAULT_LEARNER_MODEL)
    sub = getattr(args, "review_cmd", "list")

    if sub == "list":
        rows = db.execute(
            "SELECT seq, type, content, topics, correction_count FROM entries "
            "WHERE deleted=0 AND llm_processed_at IS NULL "
            "ORDER BY seq LIMIT ?",
            (getattr(args, "limit", 20),)
        ).fetchall()
        import json
        output = {
            "model": model,
            "count": len(rows),
            "entries": [{"seq": r[0], "type": r[1], "content": r[2],
                         "topics": r[3], "corrections": r[4]} for r in rows]
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
        db.close()
        return 0

    if sub == "mark":
        seq = getattr(args, "seq", None)
        if seq:
            db.execute("UPDATE entries SET llm_processed_at=datetime('now') WHERE seq=?", (seq,))
            db.commit()
            print(f"✓ seq={seq} 已标记为已处理")
        else:
            print("✗ 请指定 --seq")
        db.close()
        return 0

    return 0
COMMAND_DISPATCH = {
    "vec": cmd_vec,
    "migrate": cmd_migrate,
    "search": cmd_search,
    "list": cmd_list,
    "delete": cmd_delete,
    "update": cmd_update,
    "evolve": cmd_evolve,
    "add": cmd_add,
    "load": cmd_load,
    "export": cmd_export,
    "config": cmd_config,
    "status": cmd_status,
    "entity": cmd_entity,
    "belief": cmd_belief,
    "relation": cmd_relation,
    "review": cmd_review,
}


def main():
    """Entry point: parse arguments and dispatch to command handler."""
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)
    handler = COMMAND_DISPATCH.get(args.command)
    if handler:
        rc = handler(args)
        sys.exit(rc if rc is not None else 0)
    else:
        print(f"✗ 未知命令: {args.command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
