# 项目日志：Codex 记忆系统

> 创建: 2026-07-04 | 更新: 2026-07-04 07:30
> 状态: 设计审查中（第 5 轮）

---

## 需求清单（R1-R16）

| ID | 需求 | 优先级 | 状态 |
|:--:|------|:------:|:----:|
| R1 | 跨会话持久记忆 | 🔴 | ✅ |
| R2 | 多会话并发写入安全 | 🔴 | ✅ |
| R3 | 崩溃恢复 | 🔴 | ✅ |
| R4 | 关键词搜索 | 🔴 | ✅ |
| R5 | 语义检索 | 🔴 | ✅ |
| R6 | 写入去重 | 🔴 | ✅ |
| R7 | 知识进化 | 🔴 | ✅ |
| R8 | 矛盾检测 | 🟡 | ✅ |
| R9 | 偏好自动沉淀 | 🟡 | ⚠️ 需调整 |
| R10 | 人类可读 | 🟡 | ✅ |
| R11 | Obsidian 兼容 | 🟢 | ✅ |
| R12 | 零外部依赖部署 | 🟢 | ✅ |
| R13 | 记忆修正 | 🟡 | ✅ |
| R14 | 自动触发进化 | 🟡 | ⚠️ 待确认触发方式 |
| R15 | 进化版本管理与回滚 | 🟢 | ⚠️ 待修复 |
| R16 | 系统健康可见性 | 🟡 | ✅ |

---

## 调研纪要

调研报告: `docs/调研文档/2026-07-04-memory-system-research.md`

关键发现:
- Codex 官方有 memories 机制（~/.codex/memories/）但默认关闭且不可被外部 skill 使用
- 社区 15+ 项目验证"文件为主 + 轻量索引"是最可行方向
- Letta 基准测试: 纯文件 74% vs 专门记忆 76% — 机制不如上下文管理重要
- SQLite FTS5 对中文按 bigram 分词，精度可接受
- Claude Code 用 CLAUDE.md + auto memory，是"学习者"模式
- Codex 是"执行者"模式——设计需对齐

---

## 设计决策记录

| # | 决策 | 理由 | 替代否决的方案 |
|---|------|------|----------------|
| 1 | SQLite 唯一存储 | 消除双写一致性问题 | jsonl+SQLite（v1/v2 否决） |
| 2 | evolve 全量重写 | 避免追加劣化 | 增量 merge（会持续膨N胀） |
| 3 | FTS5 + 向量双检索 | 关键词 + 语义互补 | 仅 FTS5（R5 不满足） |
| 4 | SHA256 去重 | 确定性 + 语言无关 | FTS5 模糊匹配（不可靠） |
| 5 | system 表替代 meta | 统一运行时状态 + 审计 | 独立文件（碎片化） |
| 6 | config.toml + system 表分离 | 用户配置 vs 运行时状态 | 全部放 system（耦合配置） |
| 7 | consolidated_seq 标记策略 | 不修改 meta，记录置 NULL | 回退 consolidated_seq（浪费算力） |
| 8 | evolve 文件先写后 rename | 文件在 DB 事务后 rename | DB 事务包含 rename（不可能） |

---

## 审查历程

| 轮次 | 审查者 | 结果 | 致命 | 重要 | 关键问题 |
|:----:|:------:|:----:|:----:|:----:|----------|
| v1 | Boole | ❌ 不通过 | 15 | 24 | SQLite+jsonl 双存储方向错误 |
| v2 | Leibniz | ❌ 不通过 | 4 | 7 | SQLite 无 FTS5 无存在价值 |
| v3 | Arendt | ❌ 不通过 | 4 | 7 | 纯 jsonl 缺乏内置机制 |
| v4 | Curie | ⚠️ 条件通过 | 3 | 4 | 去掉 SQLite 是极端简化 |
| v5 | Hypatia | ⚠️ 条件通过 | 2 | 10 | SQLite 唯一存储方向确认 |
| v6 | Hume → Bacon | ✅ 通过 | 0 | 3 | R1-R13 全部满足 |
| v7 | Pascal | ⚠️ 条件通过 | 2 | 4 | 新增自我进化 + 管理（R14-R16） |

---

## 方法论错误记录

| # | 错误 | 教训 | 已修复 |
|---|------|------|:------:|
| 1 | 跳过调研直接出方案 | 先调研再设计 | ✅ 调研报告已出 |
| 2 | 存储设计跳过了使用者视角 | 设计从"谁用怎么用"开始 | ✅ 已写入方法论 |
| 3 | 一味追求简洁牺牲了长期稳健 | 平衡简洁与机制保障 | ✅ SQLite 内置机制 |
| 4 | 发起审查时缺需求列表和标准 | 必须提供需求 + 标准 + 重点 | ✅ 已写入方法论 |
| 5 | 阶段性进展未沉淀到项目文档 | 项目日志持续更新 | ✅ 本文档已创建 |

---

## 开放问题

| # | 问题 | 影响 | 建议方案 |
|---|------|------|----------|
| 1 | evolve 自动触发阻塞 session | R14 实现方式 | load 仅建议，agent 决定执行 |
| 2 | rollback 不回滚 DB | R15 完整性 | 增加 --db 选项回滚 consolidated_seq |
| 3 | config.toml 与 system 表阈值双源 | 配置不一致 | config.toml 唯一源 |

---

## 下一步

1. 修复 Pascal 审查发现的致命问题（F1 evolve 原子性、F2 _correction 类型）
2. 修复重要问题（I3-I6）
3. 提交终审
4. 终审通过后进入 writing-plans → 实施


---

## 2026-07-04 07:45 — 第 5 轮审查结果

审查者: Nash (DeepSeek-V4-Pro, high-effort)
结果: **条件通过**

### 需求满足：R1-R16 全部通过 ✅

### 修复确认
| 问题 | 结果 | 说明 |
|:----:|:----:|------|
| F1 evolve 原子性 | ✅ 已修复 | rename 在 COMMIT 后 + version 注释 |
| F2 correction 标记 | ❌ **未修复** | SQL 逻辑根本性错误: EXISTS 子查询永不为真 |
| I3 自动阻塞 | ✅ 已修复 | load 仅提示 |
| I4 ghost key | ✅ 已修复 | 并发表已修正 |
| I5 rollback | ✅ 已修复 | --db 选项 |
| I6 双阈值 | ✅ 已修复 | config.toml 唯一源 |

### F2 修复方向
entries 表加 `correction_count INTEGER DEFAULT 0` 列。
delete/update 发现 consolidated_seq 非 NULL → `SET correction_count = correction_count + 1`（不置 NULL）。
evolve step 2 捕捉条件改为 `consolidated_seq IS NULL AND correction_count = 0`。
evolve step 5 用 `CASE WHEN correction_count > 0 THEN 'user_correction' ELSE 'new' END`。

### 新发现重要问题
1. UNIQUE 索引阻止"删→加→再删" → 改为 partial index `WHERE deleted=0`
2. --rollback --db 后备份命名冲突 → 回滚时 evolve_seq 设为 VERSION

### 当前状态
- 存储位置: git/codex-memory/（Git 已初始化）
- 待修复: F2 correction_count + UNIQUE 索引 + rollback 命名
- 下一步: 修复后提交终审

### F2 已修复（2026-07-04 07:55）
- entries 表增加 correction_count 列
- delete/update 改为 SET correction_count = correction_count + 1
- evolve step 2 条件添加 AND correction_count = 0
- evolve step 5 SQL 修复为 CASE WHEN correction_count > 0
- UNIQUE 索引改为 partial index WHERE deleted=0
- rollback 修复备份命名冲突
状态: F2 已修复，待下一轮审查确认

### 2026-07-04 08:10 — 第 6 轮审查（Lovelace）
结果: 条件通过
F2 传导闭环: ✅ 四项验证全部通过
修复: evolve step 4 备份语法错误 + step 5(b) AND deleted=0
需求满足: R1-R16 全部 ✅

### 2026-07-04 — F1 删除路径修复确认 → ✅ 通过
审查者: Parfit (DeepSeek-V4-Pro, high-effort)
结果: ✅ 通过。所有致命问题全部修复，设计可进入实施。
