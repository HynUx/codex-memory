# Codex/Agent 记忆系统调研报告

> 调研时间: 2026-07-04
> 调研渠道: Tavily 多轮搜索、GitHub search、中英文社区（CSDN/腾讯云/Threads/X/Reddit/YouTube）
> 分析框架: 形式（Forms）× 功能（Functions）× 动态（Dynamics）三维分析法

---

## 一、Codex 官方记忆体系

Codex 有两层原生记忆机制：

### 1.1 AGENTS.md — 静态指令层

- Codex 的持久指令文件，等价于 Claude Code 的 `CLAUDE.md`
- 搜索路径：`~/.codex/AGENTS.md`（全局）→ 项目根目录 `AGENTS.md` → 子目录
- `AGENTS.override.md` 覆盖同级 `AGENTS.md`
- 由用户手动维护，session 启动时加载到 system prompt

### 1.2 Memories — 生成记忆层

通过 `codex features enable memories` 或 `config.toml` 的 `[features] memories = true` 开启。

**文件结构：**

```
~/.codex/memories/
├── memory_summary.md       # 短摘要，session 启动时全文读入（固定 5000 token 预算）
├── MEMORY.md               # 长格式合并记忆，按需 grep
└── rollout-summary/        # 每次 rollup 的产出
    ├── 2026-07-01-001.md
    └── ...
```

**两阶段异步架构：**

| 阶段 | 范围 | 触发条件 | 行为 |
|------|------|----------|------|
| 阶段 1 | per-thread | 会话结束 + 空闲 > `min_rollout_idle_hours`（默认 6h） | 后台提取关键词、决策、约定 → 写入 `rollout-summary/` |
| 阶段 2 | global | 阶段 1 产出一批后 | 全局锁保证不并行；读取阶段 1 输出，合入 `MEMORY.md`，更新 `memory_summary.md` |

**读取路径：**
`memory_summary.md` 全文加载（~5000 token）→ 提取关键词 → grep `MEMORY.md` → 如指向则打开对应 rollout 文件

**可配置项：** `extract_model`、`consolidation_model`、`min_rollout_idle_hours`

**已知限制：**
- EEA/英国/瑞士默认 blocked
- 纯 Markdown 文件，无向量索引
- 仅限 Codex 自身使用，不可被其他 skill 读写

---

## 二、GitHub 社区 Codex 记忆项目对比

### 2.1 项目全景

| # | 项目 | Stars | 核心方案 | 存储 | 检索 | 亮点 |
|---|------|-------|----------|------|------|------|
| 1 | **codex-memory-lite** (AKin-lvyifang) | ⭐高 | 结构化项目记忆 + 跨线程延续 | Markdown + AGENTS 配置 | 关键词 + 配置级联 | 降低 token 消耗，即插即用 |
| 2 | **codex-memory-brain** (ccycv) | ⭐高 | MCP 持久记忆 + 代码库感知 | 文件 + MCP 协议 | MCP 工具调用 | 持久层独立于 Codex |
| 3 | **memex** (strangeloopcanon) | ⭐中 | memory sidecar 模式 | 文件系统 | compact 策略 + 本地搜索 | 系统设计模式（sidecar） |
| 4 | **codex-memory** (mcncarl) | ⭐中 | Obsidian 优先 + SQLite 索引 | Markdown + SQLite | SQLite 关键词 + 人类阅读 | 人类可读 + 机器可查 |
| 5 | **codex-memory** (ponchoalv) | ⭐中 | SQLite FTS5 全文搜索 | SQLite FTS5 | 全文检索 | 极简，只做 session 搜索 |
| 6 | **CodexMemory** (le0nardomartins) | ⭐中 | Markdown + Ollama 本地 AI | Markdown + 本地 LLM | Ollama 语义处理 | 完全本地、透明、开源 |
| 7 | **memorix** (AVIDS2) | ⭐高 | 跨 agent 共享 MCP 记忆层 | MCP 共享存储 | MCP 查询 | 统一 15+ agent 的记忆 |
| 8 | **vitadex** (DavideZanonArt) | ⭐新 | 个人 OS：记忆+任务+审批 | 文件系统原生 | 按模块分类 | 一揽子工作流 + 记忆 |
| 9 | **MemSearch** (zilliztech) | ⭐1.7k | Milvus + Markdown 双存储 | Markdown + Milvus | 向量搜索 + 关键词 | 跨工具（Claude/Codex/OpenCode） |
| 10 | **codex-memory-sync** (YMY0730) | ⭐中 | AES-256 加密同步 | 文件 + 云盘/GitHub | 无专门检索 | 跨设备，加密优先 |
| 11 | **fireworks-skill-memory** (yizhiyanhua) | ⭐中 | 按 skill 分类的持久经验 | KNOWLEDGE.md | skill 级别隔离 | 每个 skill 有自己的教训库 |
| 12 | **Engram** | ⭐高 | 7 个自动收集器形成反馈环 | 文件 | 按类型分类 | 自动收集 → 蒸馏 → 回写 |

### 2.2 技术路线分布

```
文件系统 + 无索引（纯 Markdown）: ████████  (4 个项目)
文件系统 + SQLite 索引:           ██████    (3 个项目)
MCP 协议（跨 agent）:             █████     (2 个项目)
向量数据库（Milvus/Embedding）:   ███       (2 个项目)
本地 LLM（Ollama）:               ██        (1 个项目)
```

**结论：** 社区主流选择是"文件为主 + 轻量索引"，向量方案占比小。

---

## 三、Claude Code 记忆体系

### 3.1 三层记忆架构（官方）

| 层 | 文件位置 | 内容 | 维护方式 |
|----|----------|------|----------|
| 项目指令 | `CLAUDE.md`（项目根目录） | 项目约定、架构、技术栈 | 用户手动 |
| 本地覆盖 | `CLAUDE.local.md` | 本地特有指令，被 gitignore | 用户手动 |
| 自动记忆 | `~/.claude/projects/<hash>/memory/` + `MEMORY.md` | 自动积累的学习内容 | agent 自动 |

**关键命令：** `/memory` — 列出所有已加载文件，开关 auto memory

### 3.2 Cline Memory Bank（社区最流行模式）

```
memory-bank/
├── projectbrief.md      # 项目背景与目标
├── productContext.md    # 为什么存在
├── activeContext.md     # 当前工作焦点
├── systemPatterns.md    # 架构与模式
├── techContext.md       # 技术栈与配置
└── progress.md          # 进度与里程碑
```

运作：添加 `.clinerules/memory-bank.md` → 请求 "initialize memory bank" → agent 自动更新

### 3.3 Codex vs Claude Code 记忆哲学

| 维度 | Codex | Claude Code |
|------|-------|-------------|
| 角色 | **执行者（doer）** | **学习者（learner）** |
| 记忆用途 | 构建工作上下文为 goal 服务 | 沉淀经验优化行为策略 |
| 关注点 | 任务完成 | 如何完成任务 |
| 指令遵循 | **更好** | 相对较弱 |
| 自省能力 | 较弱 | **更强** |

Nicolas Bustamante 的核心洞见：

> **模型是针对其 harness 做 post-training 的。** GPT-5 针对 Codex 的 memory 层做了后训练；Claude 针对 Claude Code 的记忆层做了后训练。记忆无法在 agent 之间干净转移的根本原因在此。

---

## 四、通用 AI Agent 记忆系统对比

| 系统 | 架构 | 优势 | 劣势 | 适用场景 |
|------|------|------|------|----------|
| **Mem0** | 即插即用 + 向量嵌入 + MCP | 上手快，多级记忆 | 需要 API key | 需要语义搜索 |
| **Letta/MemGPT** | 核心记忆 + 归档记忆 | 自我修改状态，文件 74% 准确率 | 架构重 | agent 自我管理 |
| **Zep** | 时序知识图谱 | 追踪变化，关系推理 | 部署复杂 | 长项目时间维度 |
| **LangMem** | LangGraph 生态 | 深度集成 | 绑定框架 | LangChain 用户 |
| **Cognee** | 语义知识图谱 | 推理能力强 | 较重 | 企业级 |

**关键基准：** Letta 验证纯文件系统在 LoCoMo 基准达 **74% 准确率**，与专门记忆系统相差不到 2%。**记忆质量更多取决于上下文管理能力，而非存储机制。**

---

## 五、三维分析框架

来自 Steve Kinney / 学术综述，用于系统化评估记忆设计：

| 轴 | 核心问题 | 选项 |
|----|----------|------|
| **Forms（形式）** | 记忆存在哪？ | 文件 / SQLite / 向量库 / 图数据库 / MCP |
| **Functions（功能）** | 为什么需要记忆？ | 工作上下文 / 用户偏好 / 技能经验 / 项目状态 / 行为反馈 |
| **Dynamics（动态）** | 记忆如何演化？ | 追加 / 合并 / 摘要 / 冲突检测 / 淘汰 / 升级 |

---

## 六、已验证的实践与陷阱

### ✅ 已被验证有效的实践

1. **文件是第一性原理** — 人类可读、可审计、可 grep。Letta 74% 准确率、MemSearch Markdown 主存储
2. **SQLite FTS5 是最实用的索引增强** — 零额外运维，一次写入重复使用
3. **两阶段架构合理** — Codex 官方 rollout→consolidation，fireworks-skill-memory hook→flush
4. **按主题/skill 维度划分记忆** — 线性追加很快变垃圾堆，按 topic/skill 分片最实用
5. **合并阈值触发进化** — 小合并频繁 + 大合并低频的分级策略方向正确

### ❌ 已验证的陷阱

1. **不要追向量检索** — 运维负担大，收益边际递减（74% vs 76%）
2. **不要全量加载历史** — Codex 官方只加载 5000 token summary，按需 grep
3. **不要引入外部依赖** — 无意义的故障点和运维成本
4. **不要忽略冲突检测** — 矛盾记录需要标记（mcp-memory-graph authority weighting）

---

## 七、当前系统差距分析

| 维度 | 当前系统 | 社区主流 | 差距 |
|------|----------|----------|------|
| 存储层 | 3 个 flat 文件 | 多文件 + 索引（SQLite/Milvus） | 缺索引和分类 |
| 召回机制 | 全量读 profile + project-context | summary → grep → rollout 分层 | 缺分层读取路径 |
| 进化机制 | 手工合并，5/20 条阈值 | 后台自动合并（两阶段） | 缺自动化和后台进程 |
| 跨技能共享 | 无 | MCP / KNOWLEDGE.md | 缺协议/接口 |
| 冲突检测 | 无 | authority weighting | 缺矛盾标记 |
| 主题分类 | 无（线性追加） | 按 skill/topic 分片 | 缺维度划分 |
| 脚本工具 | 无 | CLI + Python API | 缺操作入口 |
| 跨会话召回 | 依赖 session 启动时全读 | 带权重的分层召回 | 缺优先级和过滤 |

---

## 八、调研结论

1. **Codex 官方记忆**提供了一套完整的"静态指令（AGENTS.md）+ 动态记忆（Memories）"框架，但 memories 默认关闭，且无法被其他 skill 使用。

2. **社区 15+ 个项目**验证了"文件为主 + 轻量索引"是最可行的方向，SQLite FTS5 是索引首选。

3. **Claude Code 的记忆哲学**更接近"学习者"模式，与我们想要的自我进化能力更匹配。可以参考其"分层记忆 + 自动积累 + `/memory` 管理"模式。

4. **不要追向量检索**：Letta 基准 + 社区选择都确认文件系统足够好。

5. **设计方向**：在现有三层基础上，增加 SQLite 索引层、主题分类、自动合并脚本、跨 skill 读写协议，形成完整的"分层记忆引擎"。

---

*本报告作为记忆系统设计的输入文档。下一步：基于调研结论提出 2-3 个架构方案，进行选型后输出 spec。*
