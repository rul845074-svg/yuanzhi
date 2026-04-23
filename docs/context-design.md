---
name: 02-06 Context 设计文档（认知镜 / 元知）
type: SOP实例
产品: 元知 YUAN · ZHI
阶段: Ⅱ 构建期
序号: 5
创建日期: 2026-04-18
v1.1 补丁: 2026-04-24
本份性质: 事后回填 + 架构演化补丁
对应文件: Obsidian vault 中 `汝霖宪法/09_Context设计文档.md`
对应步骤: 产品 SOP → Ⅱ 构建期 → 宪法 09 Context 设计文档
标签:
  - 项目总统
  - 构建期
  - Context
  - Schema
  - 认知镜
  - 元知
  - 技术细节
---

> ⚠️ **v1.1 补丁说明（2026-04-24）· 本段优先阅读**
>
> 本文档主体（一 ~ 四节 + 附 A-G）反映 **2026-04-18** 的四层 Context 架构快照。
>
> 2026-04-22 → 04-24 期间发生了工程化演化：**四层扩成五层**（M10 "跨模块共享前缀"独立成层）；**Task Context 从 5 个 prompt 扩到 9 个**（加 M4 / M8 / M5a / M5b）；**Memory Context 新增 `mirror-scale.json`**；**新增 API 层 + 前端消费层 + macOS 运维层**（原文档未涵盖）。
>
> 主体"四层划分 + 失效应对 + JSON schema"**没被推翻**（今日依然有效），但**不完整**。增量部分见末尾**附 H · Context 架构演化（2026-04-24）**。

> 📎 **对应模板**：[汝霖宪法/09_Context设计文档.md](/Users/zhanghu/汝霖/汝霖与AI的工作/汝霖宪法/09_Context设计文档.md)

# 02-06 Context 设计文档 —— 四层架构 + 全部 JSON schema（字段解释主场）

**本份为：事后回填**

> ⭐ 这是**数据模型主场**。任何新人想知道"X 字段是什么意思 / Y 文件是做什么的 / Z 关系怎么建立"，来这一份就够。

---

## 一、明确目标（5 问必答）

1. **核心问题**：让 Claude 做高质量分析，需要给它哪些上下文？这些上下文放在哪里、怎么组织、怎么保持不被污染？
   → **答**：**四层 Context**（Task / Memory / Retrieval / Conversation），全部以结构化 JSON 外挂存放在 vault 的 `可实现/系统状态/`，通过占位符注入 prompt；防污染三护栏 = **原文禁入 + 配置单源 + 幂等写入**。
2. **方向**：四层 Context 架构（Task / Memory / Retrieval / Conversation）+ 每层的物理文件 + 失效应对
3. **用户**：Claude（消费者）+ runtime（组装者）+ 作者（规则制定者）
4. **场景**：每次任务运行前，runtime 都要组装一次 context 喂给 Claude
5. **成功标准**：任何新人按本份能独立回答"X 字段是什么意思"

---

## 二、选择对象（四层 Context）

### 2.1 Task Context（任务上下文）

**职责**：告诉模型"当前在做什么任务、角色是什么、输出格式是什么、硬约束是什么"

**物理文件**：

- `prompts/daily_analysis_report.md`
- `prompts/daily_analysis_state.md`
- `prompts/ten_day_summary.md`
- `prompts/monthly_summary.md`
- `prompts/reminder_extract.md`

**关键做法**：每个任务一个轻量 prompt，不整份加载 skill 母版（token 成本 + 注意力稀释）

### 2.2 Memory Context（记忆上下文）

**职责**：告诉模型"过去发生了什么、当前有哪些已识别的模式/信念/概念"

**物理文件**：

- `cognitive_state.json` —— 模式/信念/指标/元数据
- `concept_index.json` —— 概念/意象/术语出现记录
- `suggestion_index.json` —— 建议去重追踪
- `reminders.json` —— 提醒状态
- `dimension_usage_index.json` —— 维度使用 7 天窗口
- `report_index.json` —— 所有报告索引

**关键做法**：runtime 在 `_load_existing_state()` 中逐个读取，按任务选择相关部分注入

### 2.3 Retrieval Context（检索上下文）

**职责**：拉相关历史报告/事件片段

**物理文件**：

- 最近 N 篇日报（`可实现/关于自己/每日报告/`）
- 最近 1-3 篇十日报
- 上月月报（如已生成）
- 相关概念的前 3 次出现报告（通过 concept_index 查）

**关键做法**：不全量喂给模型，按任务相关性选

### 2.4 Conversation Context（会话上下文）

**职责**：当前"对话"的原始输入

**物理文件**：

- 当日日志原文（`时间轴/日志/YYYY-MM-DD.md`）
- 飞书 moment_feed（v3 规划）

---

## 三、收集分析（全部 JSON schema · 字段解释）

### 3.1 `cognitive_state.json`（核心机器状态）

**位置**：`可实现/系统状态/cognitive_state.json`

```json
{
  "meta": {
    "profile": "dev",
    "total_analyses": 40,
    "last_updated": "2026-04-18T12:30:00+08:00",
    "latest_daily_report": "相对路径",
    "warning_count": 0
  },
  "patterns": {
    "<pattern_key>": {
      "name": "人可读模式名（例：两拍节奏）",
      "status_raw": "原始文本（保留叙事，例：松动→深度改写）",
      "status": "归一化枚举：candidate|active|aware|loosening|rewriting|dormant",
      "latest_evidence": "证据快照（抽象描述，非原文）",
      "source_report_id": "来源报告 id 引用 report_index",
      "source_report_title": "来源报告标题",
      "source_report_path": "绝对路径",
      "last_updated": "YYYY-MM-DD"
    }
  },
  "beliefs": {
    "loosening": ["信念名1", "信念名2"],
    "growing":   ["新信念1", "新信念2"]
  },
  "metrics": {
    "pattern_count": 7,
    "rewriting_count": 5,
    "loosening_count": 2
  }
}
```

**字段深度解释**：

- **`status_raw` vs `status`**：保留原文叙事同时保证机器可读。`status_raw` 是"松动→深度改写"这样的人话，`status` 是 `rewriting` 这样的枚举。两端都用。映射表在 `config/agent.config.json::pattern_status_normalization`
- **`status` 枚举映射**：候选/新出现/初现 → `candidate`；活跃/反复出现 → `active`；已觉察/看见 → `aware`；松动/减弱 → `loosening`；改写/重写中/深度改写 → `rewriting`；休眠 → `dormant`
- **`source_report_id`**：引用 `report_index.items[].id`，保持跨表关联

### 3.2 `reminders.json`（提醒状态）

**位置**：`可实现/系统状态/reminders.json`

```json
{
  "generated_at": "ISO 8601",
  "items": [
    {
      "id": "r_YYYYMMDD_NN",
      "source_report": "来源报告文件名",
      "source_type": "daily|tenday|monthly",
      "horizon": "short|medium|long",
      "title": "一句提醒标题",
      "summary": "一句摘要",
      "status": "new|active|done|snoozed|dismissed",
      "priority": "high|medium|low",
      "channel": ["dashboard", "feishu"],
      "created_at": "ISO 8601",
      "last_pushed_at": null,
      "done_at": null,
      "snooze_until": null,
      "count": 2
    }
  ]
}
```

**字段深度解释**：

- **`horizon`**：short = 本周；medium = 本月；long = 长期（季度以上）
- **`status` 状态机**：`new → active`（连续 2+ 次或首次 priority=high）/ `active → done`（用户操作）/ `done → active`（再次出现触发复发规则）/ `snoozed → active`（snooze_until 到期）
- **`count`**：该提醒重复出现的次数，用于去重和升级

### 3.3 `report_index.json`（报告快速索引）

**位置**：`可实现/系统状态/report_index.json`

```json
{
  "generated_at": "ISO 8601",
  "items": [
    {
      "id": "daily_YYYY_MM_DD | tenday_YYYY_NN | monthly_YYYY_MM",
      "type": "daily|tenday|monthly",
      "date": "YYYY-MM-DD",
      "title": "报告标题",
      "summary": "一句摘要",
      "source_path": "绝对路径",
      "tags": ["标签数组"]
    }
  ]
}
```

**字段解释**：

- **`id` 命名约定**：`<type>_<date>` 或 `<type>_<year>_<seq>`；是跨表 join 的唯一键

### 3.4 `concept_index.json`（概念索引）

**位置**：`可实现/系统状态/indexes/concept_index.json`

```json
{
  "items": [
    {
      "term": "浮萍",
      "category": "意象|物理学概念|心理学概念|玄学概念",
      "count": 3,
      "report_refs": ["daily_2026_03_12", "daily_2026_04_18"],
      "snippets": ["抽象摘要 1", "抽象摘要 2"],
      "first_seen": "YYYY-MM-DD",
      "last_seen": "YYYY-MM-DD"
    }
  ]
}
```

### 3.5 `suggestion_index.json`（建议去重）

**位置**：`可实现/系统状态/indexes/suggestion_index.json`

```json
{
  "items": [
    {
      "normalized_key": "主动展示_不求反馈",
      "title": "主动展示，不把反馈当验证",
      "count": 4,
      "first_seen": "YYYY-MM-DD",
      "last_seen": "YYYY-MM-DD",
      "report_refs": ["daily_..."],
      "related_patterns": ["two_step_rhythm"],
      "latest_status": "new|active|done|snoozed"
    }
  ]
}
```

**字段解释**：`normalized_key` 是语义归一化后的键（不是字符串匹配）；`related_patterns` 连接到 `cognitive_state.patterns.*.<key>`

### 3.6 `dimension_usage_index.json`（维度使用 7 天窗口）

**位置**：`可实现/系统状态/dimension_usage_index.json`

```json
{
  "items": [
    {
      "date": "YYYY-MM-DD",
      "psy": "CBT",
      "meta": "脉轮",
      "phy": "热力学",
      "source": "tag|keyword"
    }
  ]
}
```

**字段解释**：

- **`source`**：`tag` = 从报告尾部 `<!-- dimensions: ... -->` 解析；`keyword` = 从关键词匹配回填
- **作用**：作为下一次 daily_analysis_report 的 `{{RECENT_DIMENSIONS}}` 输入
- **大类值**：必须匹配 `config/dimensions.json` 中的大类名

### 3.7 `moment_feed.json`（规划中）

**位置**：`可实现/系统状态/moment_feed.json`

```json
{
  "items": [
    {
      "id": "m_YYYYMMDD_NN",
      "created_at": "ISO 8601",
      "source": "feishu|local",
      "tag": "情绪|灵感|观察",
      "text": "此刻内容（允许原文，但长度受限）"
    }
  ]
}
```

### 3.8 `agent.config.json`（配置单源）

**位置**：`config/agent.config.json`

结构要点：

- `profiles`：dev/prod 两套路径配置
- `tasks`：已注册任务清单（daily_analysis_report / daily_analysis_state / ten_day_summary / monthly_summary / reminder_extract）
- `paths`：vault 根、报告目录、state 目录、index 目录、dimension_usage 路径
- `pattern_status_normalization`：status 枚举映射表
- `dimensions_file`：指向 `config/dimensions.json`

### 3.9 `dimensions.json`（大类词表单源 · 2026-04-18 新增）

**位置**：`config/dimensions.json`

结构：

```json
{
  "psy":  [{"name":"CBT", "description":"...", "keywords":["CBT","认知行为"]}, ...],
  "meta": [{"name":"脉轮", "description":"...", "keywords":["脉轮","海底轮",...]}, ...],
  "phy":  [{"name":"热力学", "description":"...", "keywords":["热力学","熵",...]}, ...]
}
```

**改动规则**：改大类词表只改这一处。新增大类需同时填 `description`（给模型看）和 `keywords`（回填命中用）；改名需连带迁移 `dimension_usage_index.json` 中已有记录。

---

## 四、决策判断（四种 Context 失效应对）

### 4.1 失效应对

| 失效类型 | 识别信号 | 应对 |
|---|---|---|
| **Memory 污染** | cognitive_state 里出现原文句子 | 立即 rollback；加硬约束"原文禁入" |
| **Retrieval 过载** | prompt token 超限 | 按"最近 N 篇"裁剪；相关度排序取 top-K |
| **Task 漂移** | Prompt 逐步加约束最后超长 | Prompt 每月精简；放到 version control |
| **Conversation 断裂** | 日志文件找不到或空 | runtime 报错并停；不 fallback 瞎分析 |

### 4.2 决策

**绿灯 · 通过**。四层 Context + 全部 schema + 失效应对齐全。进入 [[02-07_验收标准四层模型]]。

---

## 附 A · 上游引用

- 上游：[[02-04_PRD]] + [[02-05_SystemPrompt规格书]]
- 和宪法接口：本份是 [[09_Context设计文档]] 在认知镜的实例

## 附 B · AI 分工表

| 任务 | AI 能做 | 人必须做 |
|---|---|---|
| Schema 草稿 | 从代码推导 | 核对真实运行数据 |
| 字段解释 | 常规语义 | 加项目特有约定（如 status_raw） |
| 失效应对 | 常见失效清单 | 判断本项目历史上真遇过哪些 |

## 附 C · 常见陷阱

1. **Schema 文档和代码漂移**——改 schema 忘改文档 = 文档作废
2. **字段命名不统一**——snake_case / camelCase 混用 = 灾难；本项目统一 snake_case
3. **原文混入 state JSON**——最硬约束，违反 = 必须立即修复

## 附 D · 质量标准 + 时间估算

- **做到位**：四层 Context + 9 个 JSON schema + 字段解释 + 失效应对
- **做过头**：把每个字段的类型用 JSON Schema 严格定义（过度工程）
- **时间**：4-5 小时

## 附 E · 下游输出

- [[02-07_验收标准四层模型]] 的功能层用 schema 做字段校验
- [[03-02_使用观察与访谈]] 用这里的 schema 判断哪些字段最常被查
- [[04-04_产品债务管理]] 用"schema 漂移"作为债务条目

## 附 F · 输出示例

见"三 · 3.1 cognitive_state.json"——一份完整 schema + 字段解释即为示例。

## 附 G · 复盘钩子

3 个月后回头问：

- schema 有没有新字段没更新到这里？
- 失效应对里哪些真触发过？怎么处理的？
- 四层 Context 的划分还是最合适的吗？要不要拆成五层？

> **G 的 6 天快速复盘（2026-04-24）**：第三问的答案是 **"要拆成五层"** —— M10 "跨模块共享前缀"作为独立一层（Prefix Context）已于 2026-04-22 加入，见附 H。前两问的演化也在附 H 里。

---

## 附 H · Context 架构演化（2026-04-24 · v1.1 补丁主场）

### H.1 一句话本质

> **Agent 模型没变**（同一个 Claude）**，Context 层数从 4 扩到 5**（加"共享前缀层"），每层**内容也扩了**（Task 多 4 份 prompt · Memory 多 1 个 JSON · 新增 API 层 + 前端层 + 运维层在 Context 之外包了一圈）。

### H.2 五层 Context（新版划分）

| 层 | 2026-04-18 版 | 2026-04-24 版 | 变化 |
|---|---|---|---|
| **1. Prefix Context**（新）| — | `prompts/_方法论前缀.md`（v3）| **新独立层** |
| **2. Task Context** | 5 份 prompt | 9 份 prompt | **+4 模块** |
| **3. Memory Context** | 6 个 JSON | 7 个 JSON（加 mirror-scale.json）| **+1** |
| **4. Retrieval Context** | 近 N 篇日报 + 月报 + concept 关联报告 | 相同 + **调度器按 M9 规则拉当期窗口**（如 M2 拉本旬 10 篇日报 + 上期十日报）| 更精确 |
| **5. Conversation Context** | 当日日志 | 相同 | **没变** |

### H.3 为什么要加"Prefix Context"第五层

原四层里**共享方法论**（身份、输出纯净、5 条语气、连续性、盲区 6 状态）分散在每份 Task prompt 里 —— 改一处要改 N 处、必然漂移。

2026-04-22 起，抽出独立 `prompts/_方法论前缀.md`：
- **engine 自动 prepend 到 narrative 类任务的 template 之前**（M1/M2/M3/M4/M5a/M5b/M8，共 7 个模块）
- **JSON 类任务（daily_analysis_state）刻意跳过注入** —— JSON 提取器的"输出纯净性"约束和叙事类前缀冲突
- 2026-04-23 D-049 完成 M1 的一次性迁移（双份过渡期收口）

**单一真相源**原则落地：改一条规则一处改，7 模块同步生效。

### H.4 Task Context 从 5 到 9（新增 4 份 prompt）

| 2026-04-18 | 2026-04-24 |
|---|---|
| daily_analysis_report | daily_analysis_report |
| daily_analysis_state | daily_analysis_state |
| ten_day_summary | ten_day_summary |
| monthly_summary | monthly_summary |
| reminder_extract | reminder_extract |
| — | **`life_growth_report.md`** (M4 · 人生轨迹) |
| — | **`next_month_astrology.md`** (M8 · 下月星象) |
| — | **`weekly_material_five.md`** (M5a · 周度素材) |
| — | **`monthly_knowledge_graph.md`** (M5b · 月末知识图谱) |

**M5 原本是单一模块**，2026-04-23 D-042 拆成 M5a（周度追加）+ M5b（月末覆盖写）——符合宪法 19.5"一个模块只做一件事"原则。

### H.5 Memory Context 新增

```json
// data/generated/mirror-scale.json（D-047 新增）
{
  "generated_at": "ISO 8601",
  "vault_root": "<absolute path>",
  "reports":          { "daily_total": 45, "ten_day_total": 5, "monthly_total": 1, "growth_exists": true },
  "material_library": { "total": 186, "categories": [ ... ] },
  "knowledge_graph":  { "concept_total": 28, "categories": [ ... ], "cross_domain_links": 4 }
}
```

**职责**：跨模块的"计数 / 累积量"规模快照，由 `scripts/generate_frontend_scale.py` 扫 vault 生成，**每次 Claude 任务跑完后 engine 自动重新生成**。

**为什么独立成文件**（不塞 cognitive_state）：
- **不跑 LLM** · 廉价 · 可频繁刷新（每次任务完都刷）
- 对应宪法 19.6"**规模 ≠ 详情**"原则：规模交给 Python 扫目录 `O(1)` · LLM 只做有观点的分析
- 前端 hover delta 动效消费这个文件（跑完 +1 之类的差值来源）

### H.6 Context 之外的三个新外壳（原文档完全没涉及）

#### H.6.1 API 层（前端消费）

| Endpoint | 方法 | 作用 |
|---|---|---|
| `/api/health` | GET | 健康检查 |
| `/api/workbench` | GET | 老 SPA 用的全量 workbench 数据 |
| `/api/mirror-scale` | GET | **新增 · 规模快照 serve** |
| `/api/agent/status` | GET | 可用任务清单 |
| `/api/agent/tasks` | GET | 任务注册表 |
| `/api/reminders` | GET | 提醒卡片 |
| `/api/agent/progress` | GET | **新增 · 实时跑任务进度**（前端 500ms poll） |
| `/api/concepts/candidates` | GET | 候选概念 |
| `/api/agent/run` | POST | **触发任务**（按 `{task, profile, date}`）|

**云端 `api_server.py` 多做一件事**：把 `/api/agent/run` 和 `/api/agent/progress` **通过反向 SSH 隧道（8774 ← 8773）转发到本机** —— 云端按钮能触发本机 Claude 跑任务，本机断线时降级为 idle 状态。

#### H.6.2 前端消费层（A 纸本观测手札）

`dist/index.html` 单文件消费：
- `/api/mirror-scale` → 首页"报告 45 / 素材 186 / 概念 28"三支柱真数据
- `/api/agent/progress` 轮询 → 嵌套进度条实时显示（外层 `2/3 · 下月星象` + 内层 `4/6 · Claude 生成中…`）
- `/api/agent/run` POST → OPS 操作台 5 按钮触发（日报/素材库/十日/月汇/人生轨迹）
- `localStorage` 持久化 → 7 天 delta hover tooltip（小红点脉动 + `+1 · 2 小时前`）

#### H.6.3 macOS 运维层（D-053 · launchd 自动化）

两个 LaunchAgent plist（`~/Library/LaunchAgents/com.yuanzhi.*.plist`）：
- `local-service`: 开机自启 8773 服务 · KeepAlive · ThrottleInterval=10s
- `reverse-tunnel`: 开机建立 SSH 反向隧道 · ServerAliveInterval=30 · CountMax=3 · ExitOnForwardFailure=yes · 断线自动重连

效果：Mac 重启 / 网络波动 / 云端重启 —— 全部自动恢复，不需要手动干预。补齐了 D-014 的 SSH 断线技术债。

### H.7 失效应对 · 扩充版

原表四类失效保留，补两类：

| 失效类型 | 识别信号 | 应对 |
|---|---|---|
| **Memory 污染** | cognitive_state 里出现原文句子 | 立即 rollback；加硬约束"原文禁入" |
| **Retrieval 过载** | prompt token 超限 | 按"最近 N 篇"裁剪；相关度排序取 top-K |
| **Task 漂移** | Prompt 逐步加约束最后超长 | Prompt 每月精简；放到 version control |
| **Conversation 断裂** | 日志文件找不到或空 | runtime 报错并停；不 fallback 瞎分析 |
| **Prefix 双份漂移**（新）| 方法论在前缀和模块 prompt 里各一份 | 双份过渡期必须有"收口日期"，到期必须删一份（D-049 M2-7 已收口）|
| **规模快照失效**（新）| `/api/mirror-scale` 返回旧时间戳 | 手动跑 `python3 scripts/generate_frontend_scale.py` 或任何 Claude 任务会自动触发刷新 |

### H.8 验收

原文"绿灯 · 通过"的四层架构依然有效。v1.1 的追加判据：

- [x] 五层 Context 都有物理承载（文件或 endpoint）
- [x] Prefix Context 单一真相源 + 双份过渡期已收口（D-049）
- [x] Memory Context 新增的 mirror-scale 有生成器 + 刷新钩子
- [x] API 层的转发机制经云端 + 反向隧道实测验证
- [x] LaunchAgent 经 Mac 重启实测自启

**v1.1 新决策：绿灯 · 通过** —— Context 架构在演化后仍符合"单一真相源 + 分层隔离 + 失效可恢复"三原则。

---

## 关联

- 上一节点：[[02-05_SystemPrompt规格书]]
- 下一节点：[[02-07_验收标准四层模型]]
- SOP 位置：模板 / 02_构建期 / (宪法接口)
- 宪法位置：[[09_Context设计文档]] 的实例化
- 项目实体：`<yuanzhi project root>`（见 [github.com/rul845074-svg/yuanzhi](https://github.com/rul845074-svg/yuanzhi)）
