---
name: memory
description: "Codex 持久记忆系统。自动加载用户画像和项目上下文，持续记录学习到的信息，跨会话保持。"
---
# Memory — Codex 自我进化记忆

本技能已集成 codex-memory 工具（SQLite 驱动）。

```bash
alias memory="python3 /Users/zhaohui/openclaw-data/git/codex-memory/scripts/memory/main.py"
```

## 三层记忆

| 层 | 文件 | 维护 |
|----|------|------|
| L1 | `~/.codex/memory/profile.md` | 手动 |
| L2 | `~/.codex/memory/project-context.md` | `memory evolve` |
| L3 | `~/.codex/memory/memory.db` | `memory add` |

## 会话启动

```bash
memory load
```

## 会话期间

```bash
memory add --type tip --content "..." --topics '["tag"]'
memory entity add --name "项目" --type project
memory relation add --subject-id 1 --predicate "使用" --object-id 2
```

## LLM 分析管道

```bash
memory review list --limit 20
# → JSON output → analyze with learner_model → 
memory belief add --content "..." --source-seqs '[1]'
memory review mark --seq 1
memory evolve
```

## 命令参考

| 命令 | 用途 |
|------|------|
| `add` | 记录条目 |
| `search` | 搜索（FTS5→LIKE→向量） |
| `evolve` | 合并到 project-context.md |
| `load` | 加载会话上下文 |
| `entity add/list` | 实体管理 |
| `belief add/list` | 信念管理 |
| `relation add/list` | 关系管理 |
| `review list/mark` | 条目分析 |
| `config set-model` | 配置模型 |
| `vec enable/rebuild/status` | 向量索引 |
| `status` | 系统状态 |
| `export` | Obsidian 导出 |

## 进化

自动触发（≥ threshold 条未合并时）：
- 重写 project-context.md（所有活跃条目）
- rebuild 向量索引
- 清理旧备份（保留最近 10 个）

config.toml:
```toml
auto_evolve_enabled = true
auto_evolve_threshold = 10
learner_model = deepseek-v4-flash
```
