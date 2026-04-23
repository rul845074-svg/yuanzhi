<div align="center">

# 元知 · YUAN · ZHI

**观测手札 · 基于 Obsidian 日志的个人认知分析系统**

*A personal cognitive mirror built on Obsidian journals, designed for the self-aware — not as an onboarding tool.*

```
每天写日志  →  Claude 按多模块节奏分析  →  报告写回 vault  →  观测手札首页呈现
   M1           M1/M2/M3/M4/M5/M8            Obsidian       A 纸本 · 元知前端
```

</div>

---

## 这是什么

元知不是一个"让你学会自省"的教学产品，而是**给已在用 Obsidian / flomo / Notion 的自省者的放大镜** —— 把散落在日记里的模式、信念、机制用 AI 分析出来、累积成长、沉淀成一份个人认知档案。

产品定位上借用"**观测手札**"的意象而非"仪表盘"：这是一本慢慢长起来的电子手札，不是一个实时监控的 SaaS dashboard。

## 设计哲学（来自[多模块系统设计](../../../汝霖宪法/19_多模块系统设计.md)8 条条款）

**① 单一真相源** · 跨模块共享的方法论只有一份正文（`_方法论前缀.md`），修改即全链路生效。

**② 调度器 ≠ 执行器** · 工作流调度员只"提醒"该跑什么，从不代替用户执行 —— 自省必须是主体行为，不可外包。

**③ 连续性 · 每个模块明确"读上一层"** · 日报读上月月汇、十日报读本旬日报 + 上期十日报 —— 不假装第一次看见。

**④ 模块间依赖显式化** · 链式（月汇 → 下月星象 → 月图谱）一键串跑；独立模块（人生轨迹）单独触发。

**⑤ 一个模块只做一件事** · M5 做两件（周度追加 + 月末图谱）就被拆成 M5a + M5b。

**⑥ 规模 ≠ 详情** · 规模快照交给 Python 扫目录（`O(1)` 计数），LLM 只做"有观点的分析"。

**⑦ Prompt 不做格式警察** · LLM 数数不准的事给 Python，严格 JSON schema 会让模型陷入 drift loop（[BC-007 教训](../../../项目2自我成长计划系统/元知/项目产出物/bug记录/BC-007_十日报新增板块drift循环.md)）。

**⑧ 命名与版本治理** · M 代号带中文名、D 号决策 3 行（决策 / 为什么 / 证据）、BC 号 bug 独立成文、废弃决策不删只追加。

## 架构

### 本地 + 云端 + 反向隧道

```
          ┌────────────────────────────────────────────────┐
          │           Obsidian vault（真相源）             │
          │  时间轴/日志 → 可实现/关于自己/报告 → 核心/…     │
          └──────────────────┬─────────────────────────────┘
                             │ 读写
┌────────────────────────────▼──────────────────────────────┐
│                      本地 Mac · localhost:8773              │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  scripts/cognitive_agent_runtime.py (engine)         │ │
│  │    ├ _build_claude_prompt (M10 前缀自动注入)          │ │
│  │    ├ claude -p (订阅额度,零成本)                       │ │
│  │    └ _refresh_mirror_scale (任务完成后自动刷规模)       │ │
│  │  scripts/工作流调度员.py (M9 提醒器 · 6 模块)            │ │
│  │  scripts/serve_cognitive_agent_demo.py (HTTP 8773)   │ │
│  └──────────────────────────────────────────────────────┘ │
│  Launch Agents (macOS 开机自启 · KeepAlive):              │
│    com.yuanzhi.local-service     ┐ 服务挂了自动重启         │
│    com.yuanzhi.reverse-tunnel    ┘ 隧道断了自动重连         │
└───────────────────────┬──────────────────────────────────┘
                        │ SSH reverse tunnel (8774 ← 8773)
                        │
┌───────────────────────▼────────────────────────────────────┐
│            云端 43.157.16.146 · nginx → 8773                │
│  deploy/cloud/api_server.py                                │
│   ├ serve /opt/cognitive-mirror/dist/ (前端)                │
│   ├ serve /opt/cognitive-mirror/data/*.json (规模快照)       │
│   └ proxy /api/agent/{run,progress} → localhost:8774 (隧道) │
└────────────────────────────────────────────────────────────┘
```

### 模块矩阵

| 代号 | 名称 | 节奏 | 产物 | 状态 |
|---|---|---|---|---|
| M0 | 全框架 | 一次性 | 架构文档 | ✅ |
| M1 | 日报 + state | 每天 | `每日报告/YYYY-MM-DD.md` + state JSON | ✅ |
| M2 | 十日报 | 10/20/30 号 | `旬度报告/YYYY_MM_AA_to_BB.md` | ✅ |
| M3 | 月汇总 | 月末 | `月度汇总/YYYY-MM.md` | ✅ |
| M4 | 人生轨迹 | 月末 M3 后 | `核心/人生轨迹总览.md`（覆盖写）| ✅ |
| M5a | 周度素材库 | 周日 | 5 份素材 md 追加 | ✅ |
| M5b | 月末知识图谱 | 月末 | 知识图谱.md（覆盖写）| ✅ |
| M6 | 盲区诊断 | 手动 | 跨全量深度扫描 | ⏸ 挂起 |
| M8 | 下月星象 | 月末 | M3 月报第十节替换 | ✅ |
| M9 | 工作流调度员 | 被动 | 提醒卡片（不执行）| ✅ |
| M10 | 方法论前缀 | 共享 | prompt 注入 | ✅ v3 |
| M11 | 正念方法库 | 月末 | 行动建议频率统计 | ⏳ 立项 |

## 技术亮点

### OPS 操作台 · 5 按钮链式任务 · 嵌套真实进度条

前端 letterhead 下方一条朱砂操作台，5 颗按钮覆盖日/周/旬/月全部手动触发场景。点击后前端每 500ms 轮询 `/api/agent/progress`，外层显示"当前链中位置（2/3 · 下月星象）"、内层显示"子任务内步骤（4/6 · Claude 生成中…）"，**文案与后端 `_update_progress` 一字不差** —— 不是前端编的假进度。

### Delta 动效两层

跑任务后前端对有变化的字段：**瞬时** 3.8 秒浮动朱砂 `+N` 徽章；**持久** localStorage 7 天的 hover tooltip（小红点脉动 + 鼠标悬停显示 `+1 · 2 小时前`）—— 刷新不丢，7 天自动清。

### 方法论前缀自动注入

所有叙事类任务（M1/M2/M3/M4/M5a/M5b/M8）的 prompt 拼接时，engine 自动 `prepend(_方法论前缀.md)`；结构化 JSON 任务（daily_analysis_state）刻意跳过注入避免污染"只输出 JSON"的约束。修改方法论一处改，六模块同步生效。

### 规模快照自动刷新

每次跑 Claude 任务成功 return 前，engine 自动触发 `generate_frontend_scale.main()` 扫 vault 重算规模，写入 `mirror-scale.json`。前端 `loadScale()` 拉到新数字后动画从旧值滑到新值 —— 零手动刷新。

### 开机自启 + 断线自动重连

macOS 原生 `launchd` 管两个 LaunchAgent：本地 8773 服务（KeepAlive · ThrottleInterval=10s）和反向 SSH 隧道（ServerAliveInterval=30 + CountMax=3 · ExitOnForwardFailure=yes）。Mac 重启 / 网络波动 / 云端重启 —— 全部自动恢复，不需要手动干预。

## 目录结构

```
元知/
├── apps/cognitive-mirror-preview/
│   ├── dist/index.html          A 纸本观测手札前端（单文件）
│   └── src/                     React 前端源码（备用）
├── config/agent.config.json     数据源 profile + 路径配置
├── deploy/cloud/api_server.py   云端薄 API（serve + proxy）
├── prompts/
│   ├── _方法论前缀.md            M10 跨模块方法论底座
│   ├── daily_analysis_report.md M1 日报
│   ├── daily_analysis_state.md  M1 state（JSON 提取器）
│   ├── ten_day_summary.md       M2 十日报
│   ├── monthly_summary.md       M3 月汇
│   ├── life_growth_report.md    M4 人生轨迹
│   ├── next_month_astrology.md  M8 下月星象
│   ├── weekly_material_five.md  M5a 周度五件套
│   └── monthly_knowledge_graph.md  M5b 月末知识图谱
├── scripts/
│   ├── cognitive_agent_runtime.py  engine
│   ├── 工作流调度员.py              M9 调度器
│   ├── serve_cognitive_agent_demo.py  本地 HTTP 服务
│   ├── generate_frontend_scale.py  规模快照生成器
│   └── sync_to_cloud.sh         云端同步脚本（dist / api / data 三模式）
└── 启动认知镜.command           本地手动启动脚本（launchd 的 fallback）
```

## 快速开始

> ⚠️ **这是作者的个人认知工具源码**，不是开箱即用的产品。prompts 里有具体的作者人名（"你是汝霖的私人日志分析助手…"）和已识别模式清单。fork 后建议做以下替换才能为自己所用：
>
> - 全局替换 `汝霖` → 你的名字
> - `prompts/daily_analysis_report.md` 里"已知核心模式"段按自己真实模式重写
> - `config/agent.config.json` 里 Obsidian vault 路径改成你的
> - `dist/index.html` 里的 FALLBACK 数据改成通用示例

### 本地运行

```bash
# 依赖：Python 3.9+ · Claude Code CLI（claude -p 命令）· Obsidian vault

# 首次：
# 1. 编辑 config/agent.config.json，指向你的 Obsidian vault
# 2. 按提示替换 prompts 里的人名与模式
# 3. 启动本地服务
python3 scripts/serve_cognitive_agent_demo.py --profile prod --port 8773

# 打开浏览器 http://127.0.0.1:8773 → letterhead 下方 OPS 操作台点按钮
```

### macOS 开机自启（可选）

```bash
# 拷贝 LaunchAgent 模板（项目里不带，自己根据 README 架构段的命名写两份 plist）
# 放到 ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.yuanzhi.local-service.plist
launchctl load -w ~/Library/LaunchAgents/com.yuanzhi.reverse-tunnel.plist
launchctl list | grep yuanzhi   # 验证
```

### 云端部署（可选）

```bash
# 前提：腾讯云/阿里云/任意 Linux 服务器 + ssh 密钥免密 + nginx 配好 80 → 8773 转发
# 修改 scripts/sync_to_cloud.sh 里的 CLOUD_HOST / CLOUD_USER / CLOUD_ROOT
./scripts/sync_to_cloud.sh           # 全量推送
./scripts/sync_to_cloud.sh --dist-only  # 只推前端
```

## 跨项目方法论沉淀

本项目的多模块协作经验已经提炼成**跨项目通用文档**，在另一个 git repo 中维护：

- `汝霖宪法/19_多模块系统设计.md` —— 抽象规则（8 条条款，本文件"设计哲学"段即这份的精简版）
- `产品SOP/模板/02_构建期/02_多模块协作设计.md` —— 施工手册（四步+八附）

下次做新的多模块 AI 产品时，这两份文档直接照搬，不需要从零摸索。

## 发展历程（简略）

| 里程碑 | 完成时 | 关键动作 |
|---|---|---|
| M0 全框架对齐 | 2026-04-22 | 10 模块清单 + 架构图 + MVP 策略 |
| M1 每日日报 | 2026-04-22 | M9 调度员 + M10 前缀骨架 + 4 场景干跑验证 |
| M2 全模块后端闭环 | 2026-04-23 | 十日 / 月汇 / 人生 / 星象 / 五件套 / 月图谱 六模块全通 · BC-007 drift 修复 |
| 前端 v1 灰度 | 2026-04-23 | A 纸本观测手札单文件 · OPS 操作台 · 双层 delta 动效 |
| M3 反哺宪法 SOP | 2026-04-24 | 多模块经验提炼成跨项目通用两份文档 |
| 云端部署 + 运维自动化 | 2026-04-24 | launchd 开机自启 + 隧道断线自动重连 |

## License

**[MIT License](LICENSE)** · Copyright (c) 2026 rul845074-svg (汝霖 · yuanzhi author)

你可以自由地 fork、修改、商用、再发布 —— 条件只有一个：**任何衍生作品必须保留 `Copyright (c) 2026 rul845074-svg (汝霖 · yuanzhi author)` 这行署名**以及 LICENSE 文件全文。

换句话说：拿走可以，改掉可以，删作者署名不可以。

> 非源码部分（prompts 里的方法论、"观测手札"产品概念、"元知 / YUAN · ZHI" 品牌名）使用上请保持相同的署名原则。如用于商业产品或学术引用，建议额外通过 GitHub issue 告知，方便未来沉淀为"用过此系统的衍生项目"索引。

