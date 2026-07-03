# Codex 记忆系统设计

> 审查轮次: 9 | 本轮: 修复 F2 correction_count 逻辑

---

## 一、需求清单

| ID | 需求 | 优先级 |
|:--:|------|:------:|
| R1 | 跨会话持久记忆 | 🔴 |
| R2 | 多会话并发写入安全 | 🔴 |
| R3 | 崩溃恢复 | 🔴 |
| R4 | 关键词搜索 | 🔴 |
| R5 | 语义检索 | 🔴 |
| R6 | 写入去重 | 🔴 |
| R7 | 知识进化（零散→结构化） | 🔴 |
| R8 | 矛盾检测 | 🟡 |
| R9 | 偏好自动沉淀 | 🟡 |
| R10 | 人类可读 | 🟡 |
| R11 | Obsidian 兼容 | 🟢 |
| R12 | 零外部依赖部署 | 🟢 |
| R13 | 记忆修正（删改+传导） | 🟡 |
| R14 | 自动触发进化 | 🟡 |
| R15 | 进化版本管理与回滚 | 🟢 |
| R16 | 系统健康可见性 | 🟡 |

---

## 二、架构

```
~/.codex/memory/
├── memory.db           # SQLite 唯一存储
├── config.toml         # 用户配置
├── profile.md          # 用户偏好（手动维护）
├── project-context.md  # evolve 全量生成
├── .backup/v{N}.bak    # evolve 前置备份
├── export/             # 可读导出
└── models/             # 嵌入模型（按需）
```

---

## 三、Schema

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA user_version=1;

CREATE TABLE entries (
    seq              INTEGER PRIMARY KEY AUTOINCREMENT,
    created          TEXT NOT NULL DEFAULT (datetime('now')),
    type             TEXT NOT NULL,            -- 应用层校验
    content          TEXT NOT NULL,
    topics           TEXT DEFAULT '[]',        -- JSON array
    sha256           TEXT NOT NULL,             -- SHA256(content||type||topics)
    deleted          INTEGER NOT NULL DEFAULT 0,
    consolidated_seq INTEGER DEFAULT NULL,     -- 被哪次 evolve 处理
    correction_count INTEGER DEFAULT 0         -- 用户修正次数（user_correction 标记依据）
);

CREATE INDEX idx_entries_type    ON entries(type, deleted);
CREATE INDEX idx_entries_created ON entries(created);
CREATE UNIQUE INDEX idx_entries_sha256 ON entries(sha256) WHERE deleted = 0;
CREATE INDEX idx_entries_deleted ON entries(deleted, consolidated_seq);

CREATE VIRTUAL TABLE entries_fts USING fts5(
    content, topics,
    tokenize='unicode61',
    content='entries', content_rowid='seq'
);
-- 3 triggers: ai 插入/ad 删除/au 更新 自动同步 FTS5

CREATE TABLE entries_vec (
    seq    INTEGER PRIMARY KEY,
    vector BLOB NOT NULL,
    model  TEXT NOT NULL,
    FOREIGN KEY (seq) REFERENCES entries(seq) ON DELETE CASCADE
);

CREATE TABLE system (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated TEXT DEFAULT (datetime('now'))
);
```

**system 初始值：** `schema_version=1`, `evolve_seq=0`, `total_adds=0`, `total_corrections=0`, `total_evolves=0`

**config.toml：**
```toml
[evolve]
suggest_threshold = 10
auto_evolve_threshold = 20     # add 自动触发阈值，达到后同步执行 evolve
[load]
max_tokens = 3000
recent_entries = 10
[vec]
enabled = false
```

---

## 四、命令

### load — 会话启动

```
读 profile.md → project-context.md → 最近 10 条有效 entries。
token 超过 3000 时截断: entries(最早的) → project-context(尾部) → profile(不动)。

project-context.md 文件不存在? → 跳过（首次兼容）。

版本校验:
  读 project-context.md 头部: <!-- evolve_seq: N -->
  如 N < system.evolve_seq → 输出"⚠️ 项目文件过期，建议 memory evolve"
  文件经过手工编辑丢失注释 → 跳过版本校验

自动触发（辅助提示，主路径走 add 自动触发）:
  未合并数 ≥ suggest_threshold → "⚠️ N 条未合并，运行 memory evolve"
  未合并数 ≥ auto_evolve_threshold × 2 → "⚠️ 未合并数已达 {N}，建议运行 memory evolve"
```

### add

```
sha256 = SHA256(content + type + topics)
BEGIN
  SELECT seq FROM entries WHERE sha256=? AND deleted=0
  IF 存在: ROLLBACK; 输出 "⏭"
  INSERT INTO entries(type, content, topics, sha256) VALUES (...)
COMMIT
UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_adds'
  -- 自动触发: 写入后检查未合并数，达到阈值直接 evolve
  -- 不走 load（避免阻塞 session），不走 agent 判断（避免遗忘）
  unmerged = SELECT count(*) FROM entries
             WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count > 0)
  IF unmerged >= auto_evolve_threshold:
      evolve()  ← 同步执行，用户等写入+进化一起完成
异步: vec → INSERT OR REPLACE entries_vec
```

### search

```
FTS5 + JOIN entries e WHERE e.deleted=0
结果 < 3 条且有向量 → entries_vec JOIN entries e WHERE e.deleted=0 → 余弦 TOP5
兜底: LIKE
参数: --limit/--offset/--type/--topic/--days
输出: 每条含 seq
```

### list — 同 search 无关键词。

### delete

```
BEGIN
  SELECT seq, consolidated_seq FROM entries WHERE seq=? AND deleted=0
  IF 未找到: ROLLBACK; exit 1
  UPDATE entries SET deleted=1 WHERE seq=?
  -- 已合并记录被删除 → 标记修正，保留 consolidated_seq 供审计
  IF consolidated_seq IS NOT NULL:
      UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?
      UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_corrections'
COMMIT
异步: DELETE FROM entries_vec WHERE seq=?
```

### update

```
BEGIN
  SELECT seq, consolidated_seq FROM entries WHERE seq=? AND deleted=0
  IF 未找到: ROLLBACK; exit 1
  new_sha256 = SHA256(new_content + type + topics)
  SELECT seq FROM entries WHERE sha256=new_sha256 AND deleted=0 AND seq!=?
  IF 碰撞: ROLLBACK; 输出"冲突"
  UPDATE entries SET content=?, type=?, topics=?, sha256=? WHERE seq=?
  IF consolidated_seq IS NOT NULL:
      UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?
      UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_corrections'
COMMIT
异步: DELETE FROM entries_vec WHERE seq=? → ONNX → INSERT OR REPLACE
```

### evolve — 知识进化

```
1. 读 system.evolve_seq → V; V = V + 1
2. 捕获未合并记录 + 已修正记录:
   SELECT seq FROM entries
   WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count > 0)
   → captured_seqs
3. 如空 → 退出
4. 备份: mkdir -p .backup; [ -f project-context.md ] && cp project-context.md .backup/v{V-1}.bak || true
5. LLM 输入:
   (a) 已有 project-context.md（文件存在时）
   (b) 未合并 + 已修正记录:
       SELECT seq, content, type, topics,
         CASE WHEN e.correction_count > 0 THEN 'user_correction'
              ELSE 'new' END AS correction_status
       FROM entries e WHERE seq IN (captured_seqs) AND e.deleted=0
   (c) 已删除修正记录（让 LLM 感知被删除的内容）:
       SELECT seq, content, type, topics,
         'user_deletion' AS correction_status
       FROM entries WHERE deleted=1 AND correction_count > 0
6. LLM 全量生成 project-context.md:
   - user_correction: 优先采纳修正版本
   - user_deletion: 从摘要中移除对应内容
   - 标记矛盾 ⚠️ + 偏好 💡
   - 嵌入版本注释: <!-- evolve_seq: V -->
7. 写临时文件（不 rename）
8. BEGIN
     UPDATE entries SET consolidated_seq=V, correction_count=0
     WHERE seq IN (captured_seqs)
     UPDATE entries SET correction_count=0 WHERE deleted=1 AND correction_count>0
     UPSERT system VALUES('evolve_seq', V, datetime('now'))
     UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_evolves'
   COMMIT
9. os.rename(tmp, project-context.md)  ← DB 成功后 rename
   （崩溃在 8-9 之间: DB 已更新但文件未 rename → load 检测 stale → 提示）
```

### evolve --rollback

```
evolve --rollback VERSION [--db]

--db 时:
  1. 检查 .backup/v{VERSION}.bak
  2. cp .backup/v{VERSION}.bak project-context.md
  3. BEGIN
       UPDATE entries SET consolidated_seq=NULL, correction_count=0
       WHERE consolidated_seq > VERSION
       UPSERT system VALUES('evolve_seq', VERSION, datetime('now'))
     COMMIT
  4. 输出 "已回滚到 v{VERSION}"

无 --db:
  仅恢复文件。
  输出 "⚠️ 文件已回滚，DB 未修改，建议 memory evolve"
```

### vec / export / status — 同上轮，不变。

---

## 五、F2 correction_count 传导逻辑校对

```
用户修正传导链路（完整闭环）:

add → evolve → entries 标记 consolidated_seq=V
  │
  ├── user update 已合并条目
  │     → correction_count += 1     （consolidated_seq 保留）
  │     → system.total_corrections += 1
  │
  ├── user delete 已合并条目
  │     → deleted=1, correction_count += 1
  │     → system.total_corrections += 1
  │
  └── 下次 evolve:
        step 2: WHERE deleted=0 AND (consolidated_seq IS NULL OR correction_count > 0)
                ↑ 捕获未合并   ↑ 捕获已修正（即使 consolidated_seq 非 NULL）
        step 5(b): correction_count>0 → 'user_correction' 标记
        step 5(c): deleted=1 AND correction_count>0 → 'user_deletion' 标记
        step 8: correction_count=0 ← 重置
```

---

## 六、并发与正确性

| 场景 | 保障 |
|------|------|
| 多 session 同时 add | WAL + busy_timeout=5000 |
| 一读一写 | WAL 不阻塞读 |
| 写入崩溃 | WAL rollback |
| evolve 期间新记录插入 | captured_seqs 冻结 → 不误标记 |
| evolve 文件-DB 不一致 | rename 在 COMMIT 后 → version 注释 stale 检测 |
| 两 session 同时 evolve | 重叠处理（v1 接受，加 fcntl.flock 后可解） |
| 向量失败 | 不阻塞 entries |
| 首次 evolve 无文件 | [ -f ] 检查跳过备份 |

---

## 七、迁移

```bash
python3 main.py migrate
# 1. 创建 memory.db + schema
# 2. 读取 learnings.jsonl (9 条) → INSERT entries
# 3. INSERT system 初始值
# 4. 输出 "已迁移 9 条 → memory evolve 初始化"
```
