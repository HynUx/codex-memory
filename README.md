# Codex Memory

持久记忆系统 — 让 AI agent 拥有跨会话的长期记忆，从零散记录自动进化为结构化知识库。

**单文件 CLI | SQLite 唯一存储 | 自动进化 | Obsidian 兼容导出**

---

## Design Philosophy

### SQLite 唯一存储，消除多源同步

不引入 JSON 文件 + DB 双写、不依赖外部存储服务。所有数据统一存放在 SQLite（WAL 模式），利用数据库内置的 ACID 事务、外键约束、FTS5 全文索引作为唯一机制。没有两套数据要同步、没有选择谁是真的问题。

### 版本化知识进化，每次都是可追溯的快照

零散学习记录通过 `evolve` 命令全量合成为结构化 Markdown 文件。每次 evolve 在 `.backup/` 下生成前置备份，文件头部嵌入版本注释。从 V1 到 VN 的每一次进化都有迹可循，回滚只需要恢复一个备份文件。

### 双检索策略，关键词 + 语义互补

FTS5 全文索引（`unicode61` 分词器）覆盖日常关键词搜索。当数据规模增长，向量搜索引擎 (`entries_vec` + 余弦相似度) 可按需启用。两种检索路径独立且互补，向量失败不阻塞全文搜索。

### 崩溃安全，三层保护

1. **WAL 模式** — 未提交事务自动回滚，进程崩溃不丢数据
2. **rename 原子性** — evolve 先将内容写入临时文件，DB 事务 COMMIT 成功后才 rename
3. **前置备份** — evolve 前自动备份当前 `project-context.md` 到 `.backup/`

### 零外部依赖，一行命令启动

Python 3 标准库自带 sqlite3、hashlib、fcntl。没有第三方包、没有外部服务、没有环境配置。克隆即用。

### 修正传导闭环

用户删除或修改已合并的记录不会失效 — 系统自动递增 `correction_count`，下次 evolve 将修正内容标记 `[user_correction]` 并全量重写。修正会传导到最终的知识输出，不会被固化在旧摘要中。

---

## Core Advantages

- **零外部依赖** — 单文件 CLI + SQLite（Python 标准库），`python3 main.py` 即运行
- **自动知识进化** — 从零散记录到结构化摘要，`add` 时 unmerged 达阈值自动触发 `evolve`
- **跨会话并发安全** — WAL 模式 + fcntl 文件锁，多 agent 同时写入不冲突
- **修正传导闭环** — 删改操作自动标记 → 下次 evolve 重处理，修正不会埋在旧摘要中
- **版本化可回滚** — 每次 evolve 前置备份，`project-context.md` 头部嵌入版本注释
- **双模式搜索** — FTS5 全文索引（默认）+ 可扩展向量语义引擎（ONNX 可选）
- **人类可读导出** — Obsidian 兼容的独立 Markdown 文件，YAML frontmatter + tags
- **自我进化** — 阈值可配置，自动触发无需人工干预
- **配置与运行分离** — `config.toml` 管理用户偏好，`system` 表管理运行时状态，互不耦合

---

## Quick Start

```bash
# 1. 本项目
cd /Users/zhaohui/openclaw-data/git/codex-memory

# 2. 首次运行（自动创建 ~/.codex/memory/ 和 memory.db）
python3 scripts/memory/main.py status

# 3. 记录第一条学习
python3 scripts/memory/main.py add --type tip --content "记忆系统已就绪" --topics '["startup"]'

# 4. 进化知识库
python3 scripts/memory/main.py evolve

# 5. 加载会话上下文（每次新会话调用）
python3 scripts/memory/main.py load
```

---

## Installation

### 作为独立工具使用

```bash
# 克隆
git clone https://github.com/HynUx/codex-memory.git
cd codex-memory

# （推荐）添加 shell 别名
echo 'alias memory="python3 $(pwd)/scripts/memory/main.py"' >> ~/.zshrc
source ~/.zshrc

# 验证
memory status
```

### 作为 Codex Skill 使用

复制 `SKILL.md` 到 Codex skills 目录，或在 project prompt 中引用。参考 `SKILL.md` 中的命令文档。

### 数据目录

所有数据存储在 `~/.codex/memory/`：

```
~/.codex/memory/
├── memory.db           # SQLite（WAL 模式）
├── config.toml         # 配置（可选）
├── profile.md          # 用户画像（手动编辑）
├── project-context.md  # evolve 输出
├── .lock               # 文件锁
├── .backup/            # evolve 前置备份
└── export/             # export 输出
```

---

## Usage

| 命令 | 用途 | 示例 |
|------|------|------|
| `add` | 记录学习 | `memory add --type workflow --content "..." --topics '["tag"]'` |
| `search` | 关键词搜索 | `memory search "并发" --limit 10` |
| `list` | 浏览记忆 | `memory list` |
| `delete` | 软删除 | `memory delete 5` |
| `update` | 修改记录 | `memory update 5 --content "新内容"` |
| `evolve` | 知识进化 | `memory evolve` |
| `load` | 加载上下文 | `memory load` |
| `export` | 导出知识库 | `memory export --dir /path/to/vault` |
| `status` | 系统状态 | `memory status` |
| `vec` | 向量索引 | `memory vec status` |
| `migrate` | 旧数据导入 | `memory migrate` |

每个命令的详细参数见 `memory <command> --help` 或 [SKILL.md](SKILL.md)。

---

## Automatic Evolution

`add` 命令在写入后检测未合并记录数，达到阈值（默认 20）时自动调用 `evolve`：

```bash
# 正常使用 — 自动进化
memory add --type tip --content "第一课"
memory add --type tip --content "第二课"
memory add --type tip --content "..."   # 如果 unmerged >= 20，自动 evolve

# 批量导入 — 跳过自动进化
memory add --type tip --content "..." --no-evolve
memory add --type tip --content "..." --no-evolve
memory evolve   # 手动触发
```

可通过 `~/.codex/memory/config.toml` 调整阈值或关闭自动进化：

```toml
auto_evolve_enabled = true
auto_evolve_threshold = 30
suggest_threshold = 15
```

---

## Maintenance

### 日常维护

```bash
# 健康检查
memory status

# 手动进化（如果自动阈值没触发）
memory evolve

# 导出知识备份
memory export --dir ~/backups/memory-$(date +%Y%m%d)
```

### 备份与恢复

**完整备份（推荐）**：
```bash
cp -r ~/.codex/memory ~/backups/memory-$(date +%Y%m%d)
```

**回滚 project-context.md**：
历史版本在 `~/.codex/memory/.backup/` 中，文件名 `v{N}.bak`。直接复制恢复：
```bash
cp ~/.codex/memory/.backup/v5.bak ~/.codex/memory/project-context.md
```

### 数据清理

已被 `delete` 软删除的记录仍占用数据库空间。SQLite 不自动回收，如需物理删除：
```bash
sqlite3 ~/.codex/memory/memory.db "DELETE FROM entries WHERE deleted=1; VACUUM;"
```

---

## Architecture

```
CLI (main.py)                   用户 / Agent
    │
    ├── add ──────────────→ INSERT entries + FTS5 同步
    │                              │
    │                    unmerged ≥ threshold ?
    │                              │
    │                    yes ──→ evolve (自动触发)
    │
    ├── evolve ───────────→ 1. acquire lock
    │                          2. 捕获未合并 + 已修正记录
    │                          3. 前置备份 → .backup/v{N}.bak
    │                          4. 全量重写 project-context.md
    │                          5. DB 更新 consolidated_seq
    │                          6. release lock
    │
    ├── search ───────────→ FTS5 → LIKE → Vector(可选)
    │
    ├── load ─────────────→ profile.md + project-context.md + 最近
    │
    ├── export ───────────→ 独立 .md (Obsidian 兼容)
    │
    └── status ───────────→ system 表计数 + 文件检查
```

### 存储层

| 表/文件 | 用途 |
|---------|------|
| `entries` | 所有学习记录（含软删除、修正计数） |
| `entries_fts` | FTS5 全文索引（触发器自动同步） |
| `entries_vec` | 向量嵌入（可选启用） |
| `system` | 运行状态：evolve_seq / total_adds / total_evolves 等 |
| `project-context.md` | evolve 输出的结构化知识摘要 |
| `profile.md` | 用户偏好画像（手动维护） |
| `config.toml` | 用户配置（自动进化阈值等） |

---

## Project Status

所有 11 个 CLI 命令在生产环境中可用。`vec enable` 和 `vec rebuild` 为占位（需集成 ONNX 嵌入模型）。

```
88 tests · 0 failures · 0 errors · 0.2s
```

---

## License

MIT

---

## Maintainer

[@HynUx](https://github.com/HynUx)
