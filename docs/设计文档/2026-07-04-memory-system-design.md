# Codex 记忆系统设计（终版）

> 版本: 6 | 审查轮次: 5 | 本轮重点: 自我进化 + 有序管理

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

SQLite 唯一运行时存储。

```
~/.codex/memory/
├── memory.db                   # 唯一存储
├── config.toml                 # 用户配置（阈值等，唯一源）
├── profile.md                  # 用户偏好（手动维护）
├── project-context.md          # 当前版本进化摘要
├── .backup/
│   ├── v0.bak
│   └── ...                     # 每次 evolve 自动备份
├── export/
└── models/
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
    type             TEXT NOT NULL,
    content          TEXT NOT NULL,
    topics           TEXT DEFAULT '[]',
    sha256           TEXT NOT NULL,
    deleted          INTEGER NOT NULL DEFAULT 0,
    consolidated_seq INTEGER DEFAULT NULL   -- 被哪次 evolve 处理
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
-- 3 triggers: ai/ad/au 自动同步

CREATE TABLE entries_vec (
    seq    INTEGER PRIMARY KEY,
    vector BLOB NOT NULL,
    model  TEXT NOT NULL,
    FOREIGN KEY (seq) REFERENCES entries(seq) ON DELETE CASCADE
);

-- 运行时状态 + 审计（不含配置）
CREATE TABLE system (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated TEXT DEFAULT (datetime('now'))
);
```

**system 初始值：**
`schema_version=1`, `evolve_seq=0`, `total_adds=0`, `total_corrections=0`, `total_evolves=0`

**config.toml（配置唯一源）：**
```toml
[evolve]
suggest_threshold = 10          # 触发提示
auto_evolve_threshold = 20      # 触发自动执行（v1 暂不实现，仅保留配置槽位）
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
token 预算 ≤3000，截断优先级: entries(去最早) → project-context(去尾部) → profile(不动)。

项目文件不存在? → 跳过（首次运行兼容）。

stale 检测:
  读 project-context.md 头部的版本注释:
    <!-- evolve_seq: 3 -->
  如注释中 evolve_seq < system.evolve_seq → 标记"项目文件过期,建议 memory evolve"

自动触发（v1: 仅提示，不自动执行）:
  未合并数 ≥ suggest_threshold → 输出 "⚠️ N 条未合并 → 运行 memory evolve 更新"
  未合并数 ≥ auto_evolve_threshold → 同上（保留配置槽位，v1 暂不自动执行）
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
异步: vec → INSERT OR REPLACE entries_vec
```

### search

```
FTS5 + JOIN entries e.deleted=0
结果 < 3 条且有向量 → entries_vec v JOIN entries e ON v.seq=e.seq WHERE e.deleted=0
兜底: LIKE
参数: --limit/--offset/--type/--topic/--days。输出含 seq。
```

### list — 同 search 无关键词。

### delete

```
BEGIN
  SELECT seq, consolidated_seq FROM entries WHERE seq=? AND deleted=0
  UPDATE entries SET deleted=1 WHERE seq=?
  IF consolidated_seq IS NOT NULL:  ← 已合并记录被修正
      UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?
      UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_corrections'
COMMIT
异步: DELETE FROM entries_vec WHERE seq=?
```

### update

```
BEGIN
  SELECT seq, consolidated_seq FROM entries WHERE seq=? AND deleted=0
  new_sha256 = SHA256(new_content + type + topics)
  SELECT seq FROM entries WHERE sha256=new_sha256 AND deleted=0 AND seq!=?
  IF 碰撞: ROLLBACK; 输出 "冲突"
  UPDATE entries SET content=?, type=?, topics=?, sha256=? WHERE seq=?
  IF consolidated_seq IS NOT NULL:
      UPDATE entries SET correction_count = correction_count + 1 WHERE seq=?
      UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_corrections'
COMMIT
异步: DELETE FROM entries_vec WHERE seq=? → ONNX → INSERT OR REPLACE
```

### evolve

```
1. SELECT value FROM system WHERE key='evolve_seq' → V
   V = int(V) + 1
2. 捕获 captured_seqs:
   SELECT seq FROM entries WHERE deleted=0 AND consolidated_seq IS NULL AND correction_count = 0
3. 如空 → 退出
4. cp project-context.md → .backup/v{V-1}.bak
5. 构建 LLM 输入:
   - 已有 project-context.md（文件存在时）
   - 未合并记录（带 correction 标记）:
     SELECT seq, content, type, topics,
       CASE WHEN EXISTS(
         SELECT 1 FROM entries AS e2
         -- e2.consolidated_seq  e2.seq = e.seq
       CASE WHEN e.correction_count > 0 THEN 'user_correction' ELSE 'new' END AS correction_status
     FROM entries e WHERE seq IN (captured_seqs)
6. LLM 生成全量 project-context.md:
   - For records marked user_correction: 优先采纳修正版本
   - 标记矛盾 ⚠️ + 偏好 💡
   - 嵌入版本注释: <!-- evolve_seq: V -->
7. 写临时文件 → （不 rename，等 DB 提交完成）
8. BEGIN
     UPDATE entries SET consolidated_seq=V WHERE seq IN (captured_seqs)
     UPSERT system VALUES('evolve_seq', V, datetime('now'))
     UPDATE system SET value=CAST(value AS INTEGER)+1 WHERE key='total_evolves'
   COMMIT
9. os.rename(tmp, project-context.md)  ← DB 事务成功后才 rename
   （崩溃在 8-9 之间: DB 已更新但文件未 rename → 下次 load 检测 stale → 提示 evolve）
```

### evolve --rollback

```
用途: 回滚 project-context.md
参数: VERSION（数字）[, --db]（同时回滚 DB）

--db 时:
  1. 检查 .backup/v{VERSION}.bak
  2. cp .backup/v{VERSION}.bak project-context.md
  3. BEGIN
       UPDATE entries SET correction_count=0, consolidated_seq=NULL WHERE consolidated_seq > VERSION
       UPSERT system VALUES('evolve_seq', VERSION, datetime('now'))
     COMMIT
  4. 输出 "已回滚到 v{VERSION}，后续记录已重置"

无 --db 时:
  1. 仅恢复文件
  2. 输出 "⚠️ 文件已回滚，DB 未修改，建议 memory evolve 重新处理"
```

### vec

```
vec.enable   — 下载 BGE-small-zh-v1.5 → 全量建索引
vec.rebuild  — 清空 entries_vec → 全量重算
vec.status   — 已索引/未索引
```

### export

```
export/ 目录可直接作为 Obsidian vault 打开。
格式: 独立 .md + frontmatter + tags + wikilinks + slugify 文件名。
```

### status

```
📊 记忆系统状态
────────────────────────
  总记录:     24 | 有效: 22 | 未合并: 14 | 已删除: 2

📈 进化追踪
  版本: v3 | 上次: 2026-07-04 06:30 | 历史: 3 个备份

🔍 搜索
  FTS5: ✅ | 向量: 342/342 (BGE-small-zh)

💾 存储
  memory.db: 128 KB | WAL: 16 KB | export: 256 KB (12 文件)
```

---

## 五、并发与正确性

| 场景 | 保障 |
|------|------|
| 多 session add | WAL + busy_timeout=5000 |
| 一读一写 | WAL 不阻塞读 |
| 写入崩溃 | WAL rollback |
| evolve LLM 期插新记录 | captured_seqs 冻结 → 不误标记 |
| **evolve 文件-DB 不一致** | rename 在 COMMIT 后 → version 注释校验 |
| evolve 中途崩溃（文件未 rename） | stale 检测 → 提示重新 evolve |
| 两 session 同时 evolve | 重叠处理（已知约束，v1 可接受） |
| 向量失败 | 不阻塞 entries |

---

## 六、迁移

```bash
python3 main.py migrate
# 1. 创建 memory.db + schema
# 2. 读取 learnings.jsonl (9 条) → INSERT entries
# 3. INSERT system 初始值
# 4. 输出 "已迁移 9 条 → memory evolve 初始化"
# 回滚: 删除 memory.db
```
