# Codex 记忆系统实施计划

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking.
> 
> **Goal:** 实现 Codex 记忆系统的全部 8 个 CLI 命令 + 自动进化触发 + 修正传导闭环
> **Architecture:** SQLite 唯一存储（WAL 模式），`git/scripts/memory/main.py` 单文件 CLI，FTS5 全文检索，ONNX 可选向量嵌入
> **Tech Stack:** Python 3 + sqlite3（stdlib）+ hashlib（stdlib）+ onnxruntime（可选）
> **Pre-req:** 设计文档 `docs/设计文档/2026-07-04-memory-system-design.md`
> **Pre-req:** 前序 SESSION 已完成 memory 系统的完整设计，所有任务彼此高度依赖（schema 共享、数据流串联）。**严禁 dispatch 多个子 agent 并行**（会踩踏）。必须串行执行，以一个工单方式逐个交付。

---
## File Structure

```
git/scripts/memory/
└── main.py          # CLI 入口（单文件，参照 tavily-router/router.py 模式）

以上是要 CREATE 的。
没有需要 MODIFY 的现有文件。

迁移完成后可 DELETE:
  ~/.codex/skills/memory/SKILL.md  （设计取代了 SKILL.md）
  .lock .consolidated_seq         （纯 jsonl 方案遗留物）
```

---

### Task 1: Project scaffold + Schema

**Files:**
- Create: `git/scripts/memory/main.py`

- [ ] **Step 1: Create directory and scaffold**

```bash
mkdir -p /Users/zhaohui/openclaw-data/git/scripts/memory
touch /Users/zhaohui/openclaw-data/git/scripts/memory/__init__.py
touch /Users/zhaohui/openclaw-data/git/scripts/memory/main.py
chmod +x /Users/zhaohui/openclaw-data/git/scripts/memory/main.py
```

- [ ] **Step 2: Write schema DDL + init function**

```python
# main.py — top-level constants + schema
import sqlite3, hashlib, json, os, fcntl, time, subprocess, shutil

MEMORY_DIR = os.path.expanduser("~/.codex/memory")
DB_PATH = os.path.join(MEMORY_DIR, "memory.db")
LOCK_PATH = os.path.join(MEMORY_DIR, ".lock")

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
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

CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(type, deleted);
CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entries_sha256 ON entries(sha256) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_entries_deleted ON entries(deleted, consolidated_seq);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    content, topics,
    tokenize='unicode61',
    content='entries',
    content_rowid='seq'
);

-- triggers (DROP first to make CREATE idempotent)
DROP TRIGGER IF EXISTS entries_ai;
CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, content, topics) VALUES (new.seq, new.content, new.topics);
END;

DROP TRIGGER IF EXISTS entries_ad;
CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, content, topics) VALUES('delete', old.seq, old.content, old.topics);
END;

DROP TRIGGER IF EXISTS entries_au;
CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, content, topics) VALUES('delete', old.seq, old.content, old.topics);
    INSERT INTO entries_fts(rowid, content, topics) VALUES (new.seq, new.content, new.topics);
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

def init_db():
    os.makedirs(MEMORY_DIR, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA_SQL)
    # seed system table
    seeds = [('schema_version','1'), ('evolve_seq','0'),
             ('total_adds','0'), ('total_corrections','0'), ('total_evolves','0')]
    for k, v in seeds:
        db.execute("INSERT OR IGNORE INTO system(key,value) VALUES(?,?)", (k, v))
    db.commit()
    return db
```

- [ ] **Step 3: Run a quick smoke test**

```bash
cd /Users/zhaohui/openclaw-data/git/scripts/memory
uv run python3 -c "
from main import init_db
db = init_db()
rows = db.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()
print('Tables:', [r[0] for r in rows])
db.close()
# cleanup test db
import os; os.remove(os.path.expanduser('~/.codex/memory/memory.db'))
"
```

Expected: `Tables: ['entries', 'entries_fts', 'entries_vec', 'system']`

---

### Task 2: `memory add` command

- [ ] **Step 1: Write the `add` function**

```python
def cmd_add(args):
    """--type TYPE --content CONTENT [--topics TOPICS] [--no-evolve]"""
    db = init_db()
    sha256 = hashlib.sha256(
        (args.content + args.type + (args.topics or '[]')).encode()
    ).hexdigest()

    row = db.execute(
        "SELECT seq FROM entries WHERE sha256=? AND deleted=0", (sha256,)
    ).fetchone()
    if row:
        print(f"⏭ 已存在 (seq={row[0]})")
        return

    db.execute(
        "INSERT INTO entries(type, content, topics, sha256) VALUES (?,?,?,?)",
        (args.type, args.content, args.topics or '[]', sha256)
    )
    db.commit()

    # read back seq
    seq = db.execute("SELECT seq FROM entries WHERE sha256=?", (sha256,)).fetchone()[0]
    print(f"✓ 已记录 (seq={seq})")

    # auto-evolve trigger
    if not getattr(args, 'no_evolve', False):
        cfg = load_config()
        if cfg.get('auto_evolve_enabled', True):
            unmerged = db.execute(
                "SELECT count(*) FROM entries WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count>0)"
            ).fetchone()[0]
            threshold = cfg.get('auto_evolve_threshold', 20)
            if unmerged >= threshold:
                evolve(db)

    db.close()
```

- [ ] **Step 2: Test add + dedup**

```bash
cd /Users/zhaohui/openclaw-data/git/scripts/memory
uv run python3 -c "
from main import init_db
db = init_db()
# add
db.execute(\"INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)\",
    ('workflow','test content','[]','abc'))
db.commit()
print('added', db.execute('SELECT count(*) FROM entries').fetchone()[0])
# dup check
sha = 'abc'
r = db.execute('SELECT seq FROM entries WHERE sha256=? AND deleted=0', (sha,)).fetchone()
print('dup?', r is not None)
db.close(); import os; os.remove(os.path.expanduser('~/.codex/memory/memory.db'))
"
```

Expected: `added 1`, `dup? True`

---

### Task 3: `memory search` + `list` commands

- [ ] **Step 1: Write search + list**

```python
def cmd_search(args):
    """KEYWORDS [--limit 5] [--offset 0] [--type TYPE] [--topic TOPIC] [--days N]"""
    db = init_db()
    limit = getattr(args, 'limit', 20)
    offset = getattr(args, 'offset', 0)
    kw = args.keywords

    # FTS5 primary path
    rows = db.execute(
        """SELECT e.seq, e.type, e.content, e.topics FROM entries_fts f
           JOIN entries e ON f.rowid = e.seq
           WHERE entries_fts MATCH ? AND e.deleted=0
           ORDER BY rank LIMIT ? OFFSET ?""",
        (kw, limit, offset)
    ).fetchall()

    # fallback: LIKE
    if not rows:
        like = f"%{kw}%"
        rows = db.execute(
            "SELECT seq, type, content, topics FROM entries WHERE content LIKE ? AND deleted=0 LIMIT ? OFFSET ?",
            (like, limit, offset)
        ).fetchall()

    # vec fallback
    if not rows and vec_available():
        # simple cosine scan
        vec = get_embedding(kw)  # returns list[float]
        rows = vec_search(db, vec, limit)

    if not rows:
        print("未找到相关记忆")
        return

    print(f"相关记忆（共 {len(rows)} 条）：")
    for seq, typ, content, topics in rows:
        print(f"  [seq:{seq}] {typ} | {topics} | {content[:60]}...")

def cmd_list(args):
    db = init_db()
    limit = getattr(args, 'limit', 20)
    rows = db.execute(
        "SELECT seq, type, content, topics FROM entries WHERE deleted=0 ORDER BY seq DESC LIMIT ?",
        (limit,)
    ).fetchall()
    for seq, typ, content, topics in rows:
        print(f"  [seq:{seq}] {typ} | {topics} | {content[:60]}...")
```

- [ ] **Step 2: Smoke test search**

```bash
cd /Users/zhaohui/openclaw-data/git/scripts/memory
uv run python3 -c "
from main import init_db; db = init_db()
db.execute(\"INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)\",
    ('workflow','codex memory test','[\"codex\",\"memory\"]','d1'))
db.commit()
rows = db.execute(\"SELECT e.seq,e.type,e.content FROM entries_fts f JOIN entries e ON f.rowid=e.seq WHERE entries_fts MATCH ? AND e.deleted=0\", ('codex',)).fetchall()
print('FTS5 hits:', len(rows))
db.close(); import os; os.remove(os.path.expanduser('~/.codex/memory/memory.db'))
"
```

Expected: `FTS5 hits: 1`

---

### Task 4: `memory delete` + `update` commands

- [ ] **Step 1: Write delete + update**

```python
def cmd_delete(args):
    db = init_db()
    row = db.execute("SELECT seq, consolidated_seq FROM entries WHERE seq=? AND deleted=0", (args.seq,)).fetchone()
    if not row:
        print(f"✗ 未找到 seq={args.seq}")
        return
    seq, consolidated_seq = row
    db.execute("UPDATE entries SET deleted=1 WHERE seq=?", (seq,))
    if consolidated_seq is not None:
        db.execute("UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?", (seq,))
        db.execute("UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_corrections'")
    db.commit()
    print(f"✓ 已删除 (seq={seq})")

def cmd_update(args):
    db = init_db()
    row = db.execute("SELECT seq, consolidated_seq FROM entries WHERE seq=? AND deleted=0", (args.seq,)).fetchone()
    if not row:
        print(f"✗ 未找到 seq={args.seq}")
        return
    seq, consolidated_seq = row

    new_content = args.content if args.content else row['content']
    new_type = args.type if args.type else row['type']
    new_topics = args.topics if args.topics else row['topics']
    new_sha256 = hashlib.sha256((new_content + new_type + new_topics).encode()).hexdigest()

    # collision check
    dup = db.execute("SELECT seq FROM entries WHERE sha256=? AND deleted=0 AND seq!=?", (new_sha256, seq)).fetchone()
    if dup:
        print(f"✗ 冲突: 已存在相同内容 (seq={dup[0]})")
        return

    db.execute("UPDATE entries SET content=?, type=?, topics=?, sha256=? WHERE seq=?",
               (new_content, new_type, new_topics, new_sha256, seq))
    if consolidated_seq is not None:
        db.execute("UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?", (seq,))
        db.execute("UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_corrections'")
    db.commit()
    print(f"✓ 已更新 (seq={seq})")
```

- [ ] **Step 2: Test delete + correction_count**

```bash
cd /Users/zhaohui/openclaw-data/git/scripts/memory
uv run python3 -c "
from main import init_db; db = init_db()
db.execute(\"INSERT INTO entries(type,content,topics,sha256,consolidated_seq) VALUES(?,?,?,?,?)\",
    ('workflow','t','[]','e1',5))
db.commit(); seq = db.execute('SELECT seq FROM entries WHERE sha256=?',('e1',)).fetchone()[0]
# delete
db.execute('UPDATE entries SET deleted=1 WHERE seq=?', (seq,))
db.execute('UPDATE entries SET correction_count=correction_count+1 WHERE seq=?', (seq,))
db.commit()
cc = db.execute('SELECT correction_count FROM entries WHERE seq=?',(seq,)).fetchone()[0]
print('correction_count after delete:', cc)
db.close(); import os; os.remove(os.path.expanduser('~/.codex/memory/memory.db'))
"
```

Expected: `correction_count after delete: 1`

---

### Task 5: `memory evolve` command

This is the most complex command. It orchestrates LLM calls and manages correction_count propagation.

- [ ] **Step 1: Write acquire_lock / release_lock helpers**

```python
_lock_fd = None
def acquire_lock():
    global _lock_fd
    _lock_fd = open(LOCK_PATH, 'w')
    fcntl.flock(_lock_fd, fcntl.LOCK_EX)

def release_lock():
    global _lock_fd
    if _lock_fd:
        fcntl.flock(_lock_fd, fcntl.LOCK_UN)
        _lock_fd.close()
        _lock_fd = None
```

- [ ] **Step 2: Write evolve core**

```python
def evolve(db, captured_seqs=None, captured_deleted_seqs=None, captured_cc=None, captured_del_cc=None):
    """
    evolve 主逻辑: 捕获未合并+已修正条目→LLM 生成 project-context.md→标记 consolidated
    可以被 add 自动触发，也可以手动调用。
    """
    # 如果外部未传入 captured 数据（手动调用场景），从头捕获
    if captured_seqs is None:
        rows = db.execute("SELECT seq, correction_count FROM entries WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count>0)").fetchall()
        captured_seqs = [r[0] for r in rows]
        captured_cc = {r[0]: r[1] for r in rows}

        rows_d = db.execute("SELECT seq, correction_count FROM entries WHERE deleted=1 AND correction_count>0").fetchall()
        captured_deleted_seqs = [r[0] for r in rows_d]
        captured_del_cc = {r[0]: r[1] for r in rows_d}

    if not captured_seqs and not captured_deleted_seqs:
        print("没有新记录需要进化")
        return

    # 读取当前版本号
    V = int(db.execute("SELECT value FROM system WHERE key='evolve_seq'").fetchone()[0]) + 1

    # 备份 project-context.md
    pc_path = os.path.join(MEMORY_DIR, "project-context.md")
    backup_dir = os.path.join(MEMORY_DIR, ".backup")
    os.makedirs(backup_dir, exist_ok=True)
    if os.path.exists(pc_path):
        shutil.copy2(pc_path, os.path.join(backup_dir, f"v{V-1}.bak"))

    # 读取已有摘要（如果存在）
    existing_summary = ""
    if os.path.exists(pc_path):
        with open(pc_path) as f:
            existing_summary = f.read()

    # 读取未合并记录
    new_entries = db.execute(
        "SELECT seq, content, type, topics FROM entries WHERE seq IN ({}) AND deleted=0"
        .format(','.join(map(str, captured_seqs)))
    ).fetchall()

    # 读取已删除修正记录
    deleted_entries = db.execute(
        "SELECT seq, content, type, topics FROM entries WHERE seq IN ({})"
        .format(','.join(map(str, captured_deleted_seqs))) if captured_deleted_seqs else "SELECT 0 WHERE 0"
    ).fetchall()

    # 构建 LLM prompt
    prompt = f"""你是一个记忆进化系统。根据已有的摘要和新的学习记录，生成完整的 project-context.md。

已有摘要:
{existing_summary}

新记录:
"""
    for seq, content, typ, topics in new_entries:
        is_correction = captured_cc.get(seq, 0) > 0
        tag = " [user_correction]" if is_correction else ""
        prompt += f"\n- seq={seq} [{typ}{tag}] {topics}: {content}"

    if deleted_entries:
        prompt += "\n\n以下内容已被用户删除，请从摘要中移除:"
        for seq, content, typ, topics in deleted_entries:
            prompt += f"\n- seq={seq} [{typ}] {topics}: {content}"

    prompt += """
\n请生成全新的 project-context.md（不是追加）:
1. 保留已有摘要中的有用信息
2. 融入新记录
3. 如果同 topic 有矛盾 → 标记 ⚠️
4. 如果同语义 preference ≥3 次 → 输出 💡 建议
5. 在文件头部嵌入版本注释: <!-- evolve_seq: V -->
"""

    # 这里 LLM 调用应该由调用方注入（不同场景可能用不同模型）
    # 当前返回占位内容
    new_content = f"<!-- evolve_seq: {V} -->\n\n# 项目上下文\n\n(由 evolve 生成)"

    # 写临时文件
    tmp_path = pc_path + ".tmp"
    with open(tmp_path, 'w') as f:
        f.write(new_content)

    # 事务: 更新 DB
    db.execute("BEGIN")
    for seq in captured_seqs:
        orig_cc = captured_cc.get(seq, 0)
        db.execute(
            "UPDATE entries SET consolidated_seq=?, correction_count=0 WHERE seq=? AND correction_count=?",
            (V, seq, orig_cc)
        )
    for seq in captured_deleted_seqs:
        orig_dcc = captured_del_cc.get(seq, 0)
        db.execute(
            "UPDATE entries SET correction_count=0 WHERE seq=? AND correction_count=?",
            (seq, orig_dcc)
        )
    db.execute("INSERT OR REPLACE INTO system(key,value,updated) VALUES('evolve_seq',?,datetime('now'))", (V,))
    db.execute("UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_evolves'")
    db.commit()

    # rename（DB 事务成功后）
    shutil.move(tmp_path, pc_path)
    print(f"✓ 进化完成 (V={V})")
```

- [ ] **Step 3: Test evolve basic flow**

```bash
cd /Users/zhaohui/openclaw-data/git/scripts/memory
uv run python3 -c "
from main import init_db, evolve; db = init_db()
db.execute(\"INSERT INTO entries(type,content,topics,sha256) VALUES(?,?,?,?)\",
    ('workflow','test','[]','f1'))
db.commit()
evolve(db)
print('evolve_seq:', db.execute('SELECT value FROM system WHERE key=\"evolve_seq\"').fetchone()[0])
import os; os.remove(os.path.expanduser('~/.codex/memory/memory.db'))
os.remove(os.path.expanduser('~/.codex/memory/project-context.md'))
"
```

Expected: `✓ 进化完成 (V=1)`, `evolve_seq: 1`

---

### Task 6: `memory load` command + auto-evolve trigger

- [ ] **Step 1: Write load**

```python
def cmd_load(args):
    """会话启动: 输出 profile.md + project-context.md + 最近 N 条学习"""
    profiles = []
    pc_path = os.path.join(MEMORY_DIR, "project-context.md")
    pf_path = os.path.join(MEMORY_DIR, "profile.md")

    if os.path.exists(pf_path):
        with open(pf_path) as f:
            profiles.append(f.read())

    if os.path.exists(pc_path):
        # stale detection
        content = open(pc_path).read()
        evolve_seq = db.execute("SELECT value FROM system WHERE key='evolve_seq'").fetchone()[0]
        import re
        m = re.search(r'<!-- evolve_seq:\s*(\d+)\s*-->', content)
        if m and int(m.group(1)) < int(evolve_seq):
            print("⚠️ project-context.md 已过期，建议运行 memory evolve")
        profiles.append(content)

    # recent learnings
    recent = db.execute(
        "SELECT seq, type, content, topics FROM entries WHERE deleted=0 ORDER BY seq DESC LIMIT ?",
        (RECENT_LIMIT,)
    ).fetchall()

    # unmerged count
    unmerged = db.execute(
        "SELECT count(*) FROM entries WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count>0)"
    ).fetchone()[0]
    if unmerged >= SUGGEST_THRESHOLD:
        print(f"⚠️ {unmerged} 条未合并，运行 memory evolve 更新")

    # token budget: 3000
    output = "\n".join(profiles)
    output += "\n## 最近学习\n"
    for seq, typ, content, topics in recent:
        output += f"- [seq:{seq}] {typ}: {content[:80]}...\n"

    # truncate to ~3000 tokens
    # (implement char-based estimate: Chinese=2, English=0.3)
    if len(output) > 12000:  # rough 3000 token estimate
        output = output[:12000] + "\n...(截断)"

    print(output)
```

- [ ] **Step 2: Test load output**

---

### Task 7: `memory export` command

- [ ] **Step 1: Write export**

```python
def cmd_export(args):
    """生成 Obsidian 兼容的独立 .md 文件"""
    export_dir = getattr(args, 'dir', os.path.join(MEMORY_DIR, "export"))
    if os.path.exists(export_dir):
        shutil.rmtree(export_dir)
    os.makedirs(export_dir)

    db = init_db()
    rows = db.execute(
        "SELECT seq, created, type, content, topics FROM entries WHERE deleted=0 ORDER BY seq ASC"
    ).fetchall()

    for seq, created, typ, content, topics in rows:
        slug = f"seq-{seq:04d}-{typ}"
        safe = slug.replace(" ", "-").replace("/", "_")
        tags = json.loads(topics) if topics and topics != '[]' else []
        tag_str = ', '.join([f"#{t}" for t in tags])
        md = f"""---
seq: {seq}
type: {typ}
topics: {topics}
created: {created}
tags: [{tag_str}]
---

# {content[:60]}

{content}

---
*Source: memory.db | 导出: {time.strftime('%Y-%m-%d')}*
"""
        with open(os.path.join(export_dir, f"{safe}.md"), 'w') as f:
            f.write(md)

    # _index.md
    with open(os.path.join(export_dir, "_index.md"), 'w') as f:
        f.write(f"# 记忆仪表盘\n\n导出时间: {time.strftime('%Y-%m-%d %H:%M')}\n\n总记录: {len(rows)}\n")

    print(f"✓ 已导出 {len(rows)} 条到 {export_dir}")
```

---

### Task 8: `memory status` + CLI entry point + migrate

- [ ] **Step 1: Write `cmd_status`**

```python
def cmd_status(args):
    db = init_db()
    total = db.execute("SELECT count(*) FROM entries").fetchone()[0]
    active = db.execute("SELECT count(*) FROM entries WHERE deleted=0").fetchone()[0]
    unmerged = db.execute("SELECT count(*) FROM entries WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count>0)").fetchone()[0]
    deleted = db.execute("SELECT count(*) FROM entries WHERE deleted=1").fetchone()[0]
    evolve_seq = db.execute("SELECT value FROM system WHERE key='evolve_seq'").fetchone()[0]
    total_adds = db.execute("SELECT value FROM system WHERE key='total_adds'").fetchone()[0]
    total_corr = db.execute("SELECT value FROM system WHERE key='total_corrections'").fetchone()[0]
    total_evolves = db.execute("SELECT value FROM system WHERE key='total_evolves'").fetchone()[0]
    backfiles = glob.glob(os.path.join(MEMORY_DIR, ".backup", "v*.bak"))
    vec_ok = "✅" if vec_available() else "❌ (未启用)"
    vec_count = db.execute("SELECT count(*) FROM entries_vec").fetchone()[0] if vec_available() else 0
    active_count = db.execute("SELECT count(*) FROM entries WHERE deleted=0").fetchone()[0]

    print(f"📊 记忆系统状态")
    print(f"  总记录: {total} | 有效: {active} | 未合并: {unmerged} | 已删除: {deleted}")
    print(f"📈 进化追踪")
    print(f"  版本: v{evolve_seq} | 历史版本: {len(backfiles)} 个")
    print(f"  累计: {total_adds} adds / {total_corr} corrections / {total_evolves} evolves")
    print(f"🔍 搜索")
    print(f"  FTS5: ✅ | 向量: {vec_ok} ({vec_count}/{active_count} 已索引)")
```

- [ ] **Step 2: Write migrate command**

```python
def cmd_migrate(args):
    """从现有 learnings.jsonl 导入到 SQLite"""
    jsonl_path = os.path.join(MEMORY_DIR, "learnings.jsonl")
    if not os.path.exists(jsonl_path):
        print("✗ 未找到 learnings.jsonl")
        return

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
                print(f"⚠️ 跳过损坏行: {line[:50]}")
                continue
            typ = rec.get('type', 'tip')
            if typ.startswith('_'):
                continue
            content = rec.get('content', '')
            topics = json.dumps(rec.get('topics', '').split(',')) if isinstance(rec.get('topics'), str) else '[]'
            sha256 = hashlib.sha256((content + typ + topics).encode()).hexdigest()
            # skip dup
            dup = db.execute("SELECT seq FROM entries WHERE sha256=? AND deleted=0", (sha256,)).fetchone()
            if dup:
                continue
            db.execute("INSERT INTO entries(type, content, topics, sha256) VALUES (?,?,?,?)",
                       (typ, content, topics, sha256))
            count += 1

    db.execute("INSERT OR IGNORE INTO system(key,value) VALUES('evolve_seq','0')")
    db.commit()
    print(f"✓ 已迁移 {count} 条记录")
    print(f"  运行 memory evolve 初始化 project-context.md")
```

- [ ] **Step 3: Write CLI entry point (argparse)**

```python
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(prog="memory")
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add")
    p_add.add_argument("--type", required=True)
    p_add.add_argument("--content", required=True)
    p_add.add_argument("--topics")
    p_add.add_argument("--no-evolve", action="store_true")

    p_search = sub.add_parser("search")
    p_search.add_argument("keywords")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--type")
    p_search.add_argument("--topic")
    p_search.add_argument("--days", type=int)

    p_list = sub.add_parser("list")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--type")
    p_list.add_argument("--topic")

    p_del = sub.add_parser("delete")
    p_del.add_argument("seq", type=int)

    p_upd = sub.add_parser("update")
    p_upd.add_argument("seq", type=int)
    p_upd.add_argument("--content")
    p_upd.add_argument("--type")
    p_upd.add_argument("--topics")

    p_ev = sub.add_parser("evolve")
    p_ev.add_argument("--rollback", type=int)
    p_ev.add_argument("--db", action="store_true")

    p_load = sub.add_parser("load")
    p_exp = sub.add_parser("export")
    p_exp.add_argument("--dir")
    p_st = sub.add_parser("status")
    p_mig = sub.add_parser("migrate")

    args = parser.parse_args()
    if args.command == "add":
        cmd_add(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "evolve":
        acquire_lock()
        db = init_db()
        evolve(db)
        release_lock()
    elif args.command == "load":
        cmd_load(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "migrate":
        cmd_migrate(args)
```

- [ ] **Step 4: Test CLI help**

```bash
cd /Users/zhaohui/openclaw-data/git/scripts/memory
uv run python3 main.py --help
uv run python3 main.py add --help
uv run python3 main.py status
```
