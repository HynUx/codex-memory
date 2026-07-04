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
import os
import sqlite3
import sys
import time

MEMORY_DIR = os.path.expanduser("~/.codex/memory")
DB_PATH = os.path.join(MEMORY_DIR, "memory.db")
LOCK_PATH = os.path.join(MEMORY_DIR, ".lock")
CONFIG_PATH = os.path.join(MEMORY_DIR, "config.toml")

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

DROP TRIGGER IF EXISTS entries_ai;
CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, content, topics)
    VALUES (new.seq, new.content, new.topics);
END;

DROP TRIGGER IF EXISTS entries_ad;
CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, content, topics)
    VALUES('delete', old.seq, old.content, old.topics);
END;

DROP TRIGGER IF EXISTS entries_au;
CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, content, topics)
    VALUES('delete', old.seq, old.content, old.topics);
    INSERT INTO entries_fts(rowid, content, topics)
    VALUES (new.seq, new.content, new.topics);
END;

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
"""

# ---- Database ---------------------------------------------------------------


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
    db.execute("UPDATE system SET value = CAST(value AS INTEGER) + 1 WHERE key = 'total_adds'")
    db.commit()

    seq = db.execute(
        "SELECT seq FROM entries WHERE sha256 = ?", (sha256,),
    ).fetchone()["seq"]
    print(f"✓ 已记录 (seq={seq})")
    db.close()
    return 0

def cmd_search(args):
    """Search memories via FTS5 with LIKE fallback."""
    db = init_db()
    kw = args.keywords
    limit = getattr(args, "limit", 5)
    offset = getattr(args, "offset", 0)

    rows = db.execute(
        """SELECT e.seq, e.type, e.content, e.topics FROM entries_fts f
           JOIN entries e ON f.rowid = e.seq
           WHERE entries_fts MATCH ? AND e.deleted=0
           ORDER BY rank LIMIT ? OFFSET ?""",
        (kw, limit, offset),
    ).fetchall()

    if not rows:
        like = "%%%s%%" % kw
        rows = db.execute(
            "SELECT seq, type, content, topics FROM entries WHERE content LIKE ? AND deleted=0 LIMIT ? OFFSET ?",
            (like, limit, offset),
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


COMMAND_DISPATCH = {
    "search": cmd_search,
    "list": cmd_list,
    "add": cmd_add,
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
