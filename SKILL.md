---
name: memory
description: "Codex 持久记忆系统。SQLite + FTS5(simple CJK) + FAISS 向量检索。跨会话自动积累、自动进化。"
---
# Memory — Codex 自我进化记忆

本技能集成 codex-memory 工具（SQLite + FTS5 + FAISS 驱动）。
所有 session 自动加载上下文，自动合并记忆。

```bash
alias memory="python3 /Users/zhaohui/openclaw-data/git/codex-memory/scripts/memory/main.py"
```

## 检索架构

三层搜索链，按优先级自动切换：
1. **向量语义** (FAISS + BGE-small-zh-v1.5) — 理解含义，不需要精确关键词
2. **中文关键词** (FTS5 + wangfenjin/simple CJK tokenizer) — 支持 jieba 级中文分词
3. **子串兜底** (LIKE) — 兜底匹配

## 会话自动流程

由 hooks + AGENTS.md 驱动，无需手动触发：
- **SessionStart**: hook 注入 SOP + profile + project-context + 最近记忆
- **Session 期间**: agent 根据触发规则调用 `memory add`
- **SessionEnd**: hook 自动 `memory evolve`，agent 可先主动收尾

## 命令参考

| 命令 | 用途 |
|------|------|
| `memory add` | 记录学习条目 |
| `memory search <关键词>` | 搜索记忆（向量 → FTS5 → LIKE） |
| `memory list` | 浏览条目 |
| `memory evolve` | 合并到 project-context.md + 重建向量索引 |
| `memory load` | 加载会话上下文 |
| `memory status` | 系统健康仪表盘 |
| `memory entity add/list` | 实体管理 |
| `memory belief add/list` | 信念管理 |
| `memory relation add/list` | 关系管理 |
| `memory vec enable/rebuild/status` | 向量索引管理 |
| `memory export` | Obsidian 兼容导出 |
| `memory config set-model` | 配置分析模型 |

## 部署要求

```bash
# 必备
python3 >= 3.10  
  
# 可选：中文分词（已集成在 ~/.codex/memory/libsimple.dylib）
# 可选：FAISS ANN 加速（pip install faiss-cpu）— 无 FAISS 时降级为 numpy cosine
# 可选：jieba 分词（pip install jieba）— simple tokenizer 已内置分词，jieba 仅备用
```

## 进化

自动触发（unmerged ≥ 10 时）：
- 合并所有条目为 project-context.md
- 重建 FAISS 向量索引
- 清理旧备份（保留最近 10 个）

手动：`memory evolve`
