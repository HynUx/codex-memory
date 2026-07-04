# codex-memory 自我进化记忆系统设计方案

> 设计版本: v1 | 基于调研报告 v3.1 | 优先级: 自我迭代 > 可靠性 > 易用性 > 最少依赖

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Agent 层 (Codex Session)                      │
│  memory load (会话启动) │ memory search (按需) │ add/delete/update   │
└────────────────────────┬────────────────────────────────────────────┘
                         │ CLI / MCP
┌────────────────────────▼────────────────────────────────────────────┐
│                       CLI 层 (main.py)                               │
│                                                                     │
│  add ──→ [auto_extract] ──→ INSERT + FTS5 ──→ check unmerged       │
│  evolve ──→ consolidate + [Beliefs analysis] ──→ project-context.md │
│          └──→ auto vec rebuild ──→ auto sync                        │
│  watch ──→ background loop (15min) ──→ auto evolve ──→ auto rebuild │
│  load ──→ profile + context + recent + health                       │
│  search ──→ FTS5 ──→ LIKE ──→ Vector (级联)                         │
│  vec enable/rebuild ──→ 向量索引管理                                 │
└────────────────────────┬────────────────────────────────────────────┘
                         │ SQLite + fcntl
┌────────────────────────▼────────────────────────────────────────────┐
│                     存储层 (SQLite WAL)                               │
│  entries   │ entries_fts │ entries_vec │ beliefs │ system            │
│  project-context.md │ profile.md │ .backup/  │ config.toml          │
└─────────────────────────────────────────────────────────────────────┘
```

### 新增组件

| 组件 | 类型 | 说明 |
|------|------|------|
| `memory watch` | 新命令 | 后台守护进程，定时检查并自动触发进化 |
| `auto_extract` | add 的增强 | `add` 时可选调用 LLM 提取实体/关系/矛盾 |
| `beliefs` 表 | 新 SQLite 表 | 存储推理结论和置信度，evolve 时更新 |
| `memory load --auto` | 增强 | 读取任务上下文后自动 search 相关记忆 |

---

## 2. memory watch — 后台自动进化守护

### 设计

```python
def cmd_watch(args):
    """Background daemon — auto health check and evolution."""
    interval = getattr(args, "interval", 15)  # minutes
    
    while True:
        time.sleep(interval * 60)
        db = init_db()
        cfg = load_config()
        
        if not cfg["auto_evolve_enabled"]:
            continue
        
        unmerged = db.execute(
            "SELECT count(*) FROM entries WHERE deleted=0 "
            "AND (consolidated_seq IS NULL OR correction_count>0)"
        ).fetchone()[0]
        
        if unmerged >= cfg["auto_evolve_threshold"]:
            db.close()
            cmd_evolve(None)  # 内部包含 auto vec rebuild
        else:
            db.close()
```

### 关键设计决策

- **interval 默认 15 分钟**：小时级时效性 + 不过度消耗资源
- **复用 cmd_evolve**：不重复实现进化逻辑，evolve 内部已包含 auto vec rebuild
- **无外部依赖**：纯 Python，使用 `time.sleep` + 信号处理
- **优雅退出**：捕获 SIGINT/SIGTERM，释放资源后退出
- **并发安全**：cmd_evolve 内部有 fcntl lock，多个 watch 实例不会冲突

### 新增 argparse 配置

```python
p = sub.add_parser("watch", help="后台自动进化守护")
p.add_argument("--interval", type=int, default=15, help="检查间隔(分钟)")
p.add_argument("--daemonize", action="store_true", help="后台运行")
```

---

## 3. auto_extract — 自动实体/关系提取

### 设计原则

- **不阻塞 add**：提取失败不影响记录写入
- **可配置 LLM endpoint**：通过 config.toml 配置，不硬编码
- **提取结果存入独立的 `entities` 和 `relations` 表**
- **提取是辅助 add 的增强，不是替代 add**

### LLM 调用接口

config.toml 新增：

```toml
[extract]
enabled = false  # 默认关闭，用户 opt-in
endpoint = "http://localhost:11434/api/generate"  # Ollama 示例
model = "qwen2.5:7b"
timeout = 10
```

### 提取流程

```
memory add --content "用户偏好 Python 异步编程"
  │
  ├── 检查 config.extract.enabled?
  │    ├── 否 → 跳过
  │    └── 是 → POST 到 LLM endpoint
  │              Prompt: "从以下文本中提取实体和关系，输出 JSON"
  │              Response: {
  │                "entities": [
  │                  {"name": "用户", "type": "person", "value": "偏好 Python 异步"},
  │                  {"name": "Python 异步编程", "type": "skill", "value": "偏好"}
  │                ],
  │                "relations": [
  │                  {"subject": "用户", "predicate": "偏好", "object": "Python 异步编程"}
  │                ]
  │              }
  │
  ├── 写入 entries 表（核心流程，不受 LLM 影响）
  ├── 如果提取成功 → 写入 entities + relations 表
  ├── 如果提取失败 → 仅打印警告，不阻塞
  └── 继续 auto-evolve 检查
```

### 新增 SQLite 表

```sql
CREATE TABLE IF NOT EXISTS entities (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT NOT NULL,
    type     TEXT NOT NULL,       -- person / skill / preference / tool / ...
    values   TEXT NOT NULL DEFAULT '[]',  -- JSON array: [{"value": "...", "source_seq": 12}]
    created  TEXT DEFAULT (datetime('now')),
    updated  TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_unique ON entities(name, type);

CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities
BEGIN
    UPDATE entities SET updated = datetime('now') WHERE id = new.id;
END;

CREATE TABLE IF NOT EXISTS relations (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    subject   TEXT NOT NULL,       -- entity name
    predicate TEXT NOT NULL,       -- 偏好/工作于/使用/...
    object    TEXT NOT NULL,       -- entity name
    source_seq INTEGER,
    created   TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (source_seq) REFERENCES entries(seq) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_relations_subject ON relations(subject);
CREATE INDEX IF NOT EXISTS idx_relations_predicate ON relations(predicate);
```

### 并发安全

- extract 的 LLM 调用是纯读取操作，不涉及写锁
- entities/relations 表的写入在 cmd_add 的同一个连接中完成，受 SQLite WAL 保护
- 多个 agent 同时 add + extract 不会数据损坏（WAL + auto-increment PK）

---

## 4. Beliefs 层

### 设计

源自调研的 Hindsight 四网络中的"Evolving Beliefs"。是 evolve 过程中的推理步骤。

```sql
CREATE TABLE IF NOT EXISTS beliefs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    content      TEXT NOT NULL,
    source_seqs  TEXT NOT NULL,       -- JSON 数组 [seq1, seq2, ...]
    confidence   REAL DEFAULT 0.5,   -- 0.0 ~ 1.0
    previous_id  INTEGER DEFAULT NULL, -- 前序版本（支持回滚追溯）
    evolve_seq   INTEGER NOT NULL,    -- 在哪次 evolve 中生成的
    created      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (previous_id) REFERENCES beliefs(id),
    FOREIGN KEY (evolve_seq) REFERENCES system(value)  -- 逻辑关联
);
```

### Beliefs 生成时机

在 `cmd_evolve` 内，完成 consolidate 后、写入 project-context.md 前：

```python
def cmd_evolve(args):
    acquire_lock()
    try:
        db = init_db()
        # ... 现有逻辑：捕获未合并+已修正记录 ...
        # ... 写入 project-context.md ...
        
        # [新增] Beliefs 推理
        if cfg.get("beliefs_enabled", False):
            analyze_contradictions(db, captured_seqs, cfg)
        
        # [现有] auto vec rebuild
        if embed.is_available():
            ...
        
        db.close()
    finally:
        release_lock()
```

### 矛盾检测策略

注意：当前实现聚焦于**单条目高争议检测**。跨条目矛盾分析需要 LLM 增强（方案 2）。

```python
def analyze_and_mark_high_controversy(db, captured_seqs, cfg):
    """检测高争议条目并写入 beliefs 表 (per-entry only)。"""
    for seq in captured_seqs:
        row = db.execute(
            "SELECT correction_count, content FROM entries WHERE seq=?",
            (seq,)
        ).fetchone()
        cc = row["correction_count"]
        if cc < 2:
            continue
        # confidence 随修正次数衰减
        confidence = max(0.0, 1.0 - cc * 0.3)
        db.execute(
            "INSERT INTO beliefs(content, source_seqs, confidence, evolve_seq) "
            "VALUES(?, ?, ?, (SELECT value FROM system WHERE key='evolve_seq'))",
            (f"seq={seq}: high-controversy ({cc} corrections)",
             json.dumps([seq]), confidence)
        )
    
    # 方案 2：LLM 增强 (optional, 需配置 [beliefs] section)
    beliefs_cfg = cfg.get("beliefs", {})
    if beliefs_cfg.get("enabled", False) and len(captured_seqs) >= 2:
        llm_contradiction_analysis(db, captured_seqs, beliefs_cfg)
```

### project-context.md 输出格式

```
<!-- evolve_seq: 5 -->

# 项目上下文

## 已确认知识

- seq=12 [workflow]: SQLite WAL 模式确保并发安全
- seq=15 [tip]: 标记删除的记录不会释放磁盘空间

## 存在分歧

- ⚠️ seq=18: "部署流程"被反复修正 3 次（correction_count=3），置信度降至 0.1
  [Belief id=7] 该条目的内容可能不稳定，建议人工复核

## 已删除

- seq=10: ~~旧版本的部署流程~~
```

---

## 5. auto vec rebuild — evolve 后自动同步向量索引

### 设计

已在 v1 中设计（见之前的 `main.py` 修改），待审查通过后合并：

- auto-extract 新增 entities/relations 表也需要向量化——这些应该与 entries 向量分开还是合并？
- **决策：先分开**。entities 的语义与 entries 不同，分开检索更清晰。后续可通过 `search` 的合并策略组合结果

```python
# 在 cmd_evolve 完成后调用
if embed.is_available():
    unindexed = db.execute(
        "SELECT count(*) FROM entries e LEFT JOIN entries_vec v "
        "ON e.seq=v.seq WHERE e.deleted=0 AND v.seq IS NULL"
    ).fetchone()[0]
    if unindexed > 0:
        cmd_vec(None)  # 等价于 vec rebuild
```

---

## 6. auto-retrieval — 会话上下文自动注入

### 分层设计

**前提**：memory CLI 工具本身无法注入到 Agent 推理循环。需要分层实现：

| 层 | 做什么 | 谁负责 |
|----|--------|--------|
| CLI 工具 | 提供 stdin 输入检索能力 | memory CLI |
| SKILL.md | 约束 Agent 在关键节点自动调用 search | 文档化 |
| MCP 服务(可选) | 在推理循环中自动暴露相关记忆 | 增强层 |

### CLI 层面

`memory search` 支持从 stdin 读取检索上下文：

```bash
echo "当前任务：修复数据库连接池泄漏" | memory search --stdin --limit 5
```

`memory load` 增强：

```bash
# 在 session 启动时调用，输出上下文 + 自动搜索与项目最相关的记录
memory load --auto-search "\`cat /tmp/current_task.txt\`"
```

---

## 7. 实施计划与依赖评估

### 新增依赖

| 组件 | 所需外部依赖 | 依赖成本 | 用户是否可见 |
|------|-------------|---------|------------|
| memory watch | 无（Python stdlib） | 零 | 否 |
| auto vec rebuild | sentence-transformers（已安装） | ~200MB 模型 | 向量搜索已有 |
| auto extract | LLM endpoint（外部服务） | 无新增库依赖 | config.toml 中配置 |
| Beliefs (规则) | 无 | 零 | 否 |
| Beliefs (LLM) | LLM endpoint | 与 auto extract 共享 | 同一配置 |
| auto retrieval | 无 | 零 | 否 |

### 实施优先级

| Phase | 内容 | 预估工时 | 依赖 |
|-------|------|---------|------|
| **P0** | memory watch + auto vec rebuild（命令行已有设计） | 0.5 天 | 无 |
| **P1** | beliefs 表 + evolve 集成（规则方案） | 1 天 | P0 |
| **P2** | auto extract + entities/relations 表 | 1.5 天 | 无（与 P0/P1 独立）|
| **P3** | Beliefs LLM 增强 + 数据清理策略 | 1 天 | P1 + P2 |
| **P4** | auto retrieval 增强（stdin + --auto-search） | 1 天 | P0b |

### 并发安全总览

| 场景 | 保护机制 | 说明 |
|------|---------|------|
| 多 agent 同时 add | WAL + 独立连接 | 读不阻塞写，写不阻塞读 |
| 多 agent 同时 evolve | fcntl.flock(LOCK_EX) | 同一时间只有一个 evolve 执行 |
| add 过程中 evolve 触发 | add 检查阈值后返回，不等待 evolve 完成；evolve 由 watch 或异步标记触发 | 避免 add 命令因 evolve 锁而长期阻塞 |
| watch + add 同时触发 | watch 获取 lock 后兜底 | watch 发现 unmerged=0 时跳过 evolve |
| auto extract + write | 同一连接内完成 | LLM 调用超时不影响数据库写入 |
