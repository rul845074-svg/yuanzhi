#!/usr/bin/env python3
"""
M9 工作流调度员 · 提醒器版（M2 里程碑 v4 · 含 M5a/M5b 拆分）

职责：给定一个日期，判断今天是否是 M2/M3/M4/M5a/M5b/M8 的节点，
      如果是就提醒用户"今天到 X 节点了，要不要跑 X 模块"。

定位说明：
- M9 是"提醒器"不是"执行器"——只告诉你今天该注意什么，不真跑模型。
- M1 每日报告 和 M6 盲区诊断 由用户手动触发（前端 / 终端），不归 M9 管。
- M9 管的 6 个自动化节点模块：
  · M2 十日报告（10/20/30）
  · M3 月度汇总（月末连体 1/4）
  · M4 人生成长报告（月末连体 2/4）
  · M8 下月星象（月末连体 3/4）
  · M5b 知识图谱（月末连体 4/4）
  · M5a 素材库五件套（周日）

触发方式（两种）：
1. 被动：M1 跑完后 engine 自动串调 M9（engine 对接留给 M2 里程碑）
2. 主动：用户独立跑 `python 工作流调度员.py --date XXX`（查某天该做什么 / 调试）

边界（M1 里程碑暂不做）：
- 不实际调用 Claude API 跑模型
- 不写入 Obsidian
- 不对接 M1 engine 的"跑完后串调"

用法示例：
    # 4/22 周三：无提醒（今天没有自动化节点）
    python3 scripts/工作流调度员.py --date 2026-04-22

    # 4/19 周日：提醒 M5 素材库
    python3 scripts/工作流调度员.py --date 2026-04-19

    # 4/20 十日节点：提醒 M2 十日报告
    python3 scripts/工作流调度员.py --date 2026-04-20

    # 4/30 月末：提醒 M2 + 月末连体四兄弟 M3/M4/M8/M5b（共 5 条）
    python3 scripts/工作流调度员.py --date 2026-04-30

    # 输出某模块拼好的完整 prompt（前缀 + 模块专属 prompt）
    python3 scripts/工作流调度员.py --module M3_月度汇总 --show-prompt
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = ROOT / "prompts"
METHODOLOGY_PREFIX = PROMPTS_DIR / "_方法论前缀.md"


# 模块注册表：M9 管 6 个自动化节点模块
# （M1 每日报告 / M6 盲区诊断 由用户手动触发，不在这里）
MODULES = {
    "M2_十日报告": {
        "prompt": "ten_day_summary.md",
        "trigger_name": "十日节点（10/20/30）",
        "description": "读取当十日 10 篇日报（月内非首期时追加上期十日报，仅用于能力对比表左列），输出十日报告。31 号的日志归月报不归十日报。",
    },
    "M3_月度汇总": {
        "prompt": "monthly_summary.md",
        "trigger_name": "月末连体（月最后一天）",
        "description": "读本月 2-3 个十日报 + 上月月汇总，输出本月月度汇总（前 9 节；第十节「下月星象参考」由 engine 追加占位、M8 下月星象填内容）",
    },
    "M4_人生成长报告": {
        "prompt": "life_growth_report.md",
        "trigger_name": "月末连体（月最后一天）",
        "description": "读取上版人生轨迹总览 + 本月月汇总，输出新版总览（旧内容一字不动+本月塑造性新增融入 6 大板块），engine 先备份再覆盖写 核心/人生轨迹总览.md",
    },
    "M5a_素材库五件套": {
        "prompt": "weekly_material_five.md",
        "trigger_name": "周度（周日）",
        "description": "读本周 7 天日报（少于 3 篇则跳过），按金句/主题线索/场景片段/原创洞察/思维差异五件套提取增量段，engine 用分段标记语法按锚点智能追加到 5 个素材库文件。",
    },
    "M8_下月星象": {
        "prompt": "next_month_astrology.md",
        "trigger_name": "月末连体（月最后一天）",
        "description": "读上月月报末尾「对本月预测」+ 本月月汇总，先做信用校准再查下月天象，替换本月月报末尾第十节占位段（不覆盖前 9 节）。下月 M1 每日报告读本月月报时自然拿到星象参考。",
    },
    "M5b_知识图谱": {
        "prompt": "monthly_knowledge_graph.md",
        "trigger_name": "月末连体（月最后一天）",
        "description": "读当前知识图谱 + 本月 5 件套增量 + 本月月汇总，输出整份新版知识图谱（旧节点一字不动 + 本月新节点/新连接融入物理/认知/心理三象限），engine 备份后覆盖写。",
    },
}


# ---------------- 日期判断辅助函数 ----------------

def is_last_day_of_month(d: date) -> bool:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.day == last


def is_sunday(d: date) -> bool:
    return d.weekday() == 6  # Monday=0 ... Sunday=6


def is_ten_day_node(d: date) -> bool:
    """十日节点 = 固定 10 / 20 / 30。31 号的日志归月报（由月末连体触发）,不是十日节点。
    2 月（28/29 天）没有第三个十日节点——2 月下旬日志全部归月报。"""
    return d.day in (10, 20, 30)


# ---------------- 提醒判断主逻辑 ----------------

def decide_reminders(today: date) -> list[dict]:
    """按当日日期判断该提醒哪些模块。返回按时间顺序排序的提醒列表。"""
    reminders: list[dict] = []

    # 1. M5a 素材库五件套——周日
    if is_sunday(today):
        reminders.append({
            "module": "M5a_素材库五件套",
            "reason": f"{today} 是周日",
            "action": "要不要跑本周素材库五件套提取？（手动决定）",
        })

    # 2. M2 十日报告——固定 10 / 20 / 30（不是"月最后一天"——31 号归月报）
    if is_ten_day_node(today):
        reminders.append({
            "module": "M2_十日报告",
            "reason": f"{today} 是十日节点，day={today.day}",
            "action": "要不要跑本十日总报告？（手动决定）",
        })

    # 3. M3 / M4 / M8 / M5b 月末连体四兄弟——月最后一天
    # 跑动顺序：M3 → M4 → M8 → M5b
    # （M3 先生成本月月汇总，M4 读月汇总更新总览，M8 读月汇总写第十节，M5b 读月汇总 + 5 件套增量更新知识图谱）
    if is_last_day_of_month(today):
        reminders.append({
            "module": "M3_月度汇总",
            "reason": f"{today} 是月最后一天，月末连体 1/4",
            "action": "要不要跑本月月度汇总？（手动决定）",
        })
        reminders.append({
            "module": "M4_人生成长报告",
            "reason": f"{today} 是月最后一天，月末连体 2/4",
            "action": "要不要更新人生成长轨迹总览？（手动决定）",
        })
        reminders.append({
            "module": "M8_下月星象",
            "reason": f"{today} 是月最后一天，月末连体 3/4",
            "action": "要不要查下月星象并替换本月月报末尾第十节？（手动决定）",
        })
        reminders.append({
            "module": "M5b_知识图谱",
            "reason": f"{today} 是月最后一天，月末连体 4/4",
            "action": "要不要整合本月 5 件套 + 月汇总更新知识图谱？（手动决定）",
        })

    return reminders


# ---------------- Prompt 拼接 ----------------

def compose_prompt(module_key: str) -> tuple[str, bool, str]:
    """返回 (完整 prompt, 是否就绪可跑, 状态说明)"""
    spec = MODULES[module_key]

    if not METHODOLOGY_PREFIX.exists():
        return "", False, f"[阻塞] 方法论前缀文件不存在: {METHODOLOGY_PREFIX}"

    prefix = METHODOLOGY_PREFIX.read_text(encoding="utf-8")

    prompt_file = spec["prompt"]
    if prompt_file is None:
        return "", False, f"[待建] {module_key} 的 prompt 还没建（M2 里程碑才建）"

    module_prompt_path = PROMPTS_DIR / prompt_file
    if not module_prompt_path.exists():
        return "", False, f"[阻塞] 模块 prompt 文件不存在: {module_prompt_path}"

    module_prompt = module_prompt_path.read_text(encoding="utf-8")
    full_prompt = (
        f"{prefix}\n\n"
        f"---\n\n"
        f"# 模块专属 prompt · {module_key}\n\n"
        f"{module_prompt}"
    )
    return full_prompt, True, "[就绪]"


# ---------------- CLI 主入口 ----------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="M9 工作流调度员 · 提醒器（M1 里程碑 v2）",
    )
    parser.add_argument("--date", default=None,
                        help="要查的日期（YYYY-MM-DD），默认=今天")
    parser.add_argument("--show-prompt", action="store_true",
                        help="连同拼好的完整 prompt 一起输出（只对就绪模块有效）")
    parser.add_argument("--module", default=None,
                        choices=list(MODULES.keys()),
                        help="强制看指定模块的拼接结果（忽略日期判断）")
    args = parser.parse_args()

    today = (datetime.strptime(args.date, "%Y-%m-%d").date()
             if args.date else date.today())

    # 如果指定了 --module，直接展示该模块的拼接结果（用于调试 / 预览 prompt）
    if args.module:
        full_prompt, runnable, status = compose_prompt(args.module)
        entry = {
            "mode": "module-preview",
            "module": args.module,
            "trigger_name": MODULES[args.module]["trigger_name"],
            "description": MODULES[args.module]["description"],
            "status": status,
            "runnable": runnable,
        }
        if runnable:
            entry["prompt_byte_length"] = len(full_prompt.encode("utf-8"))
            entry["prompt_preview"] = full_prompt[:150].replace("\n", " ") + "..."
            if args.show_prompt:
                entry["prompt_full"] = full_prompt
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return

    # 按日期判断今天有无提醒
    reminders = decide_reminders(today)

    result = {
        "date": today.isoformat(),
        "weekday": today.strftime("%A"),
        "date_flags": {
            "is_sunday": is_sunday(today),
            "is_ten_day_node": is_ten_day_node(today),
            "is_last_day_of_month": is_last_day_of_month(today),
        },
        "reminder_count": len(reminders),
    }

    if not reminders:
        result["message"] = f"{today} 没有自动化节点，专心写日报就好（M1 由你手动触发）。"
        result["reminders"] = []
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    result["message"] = f"{today} 有 {len(reminders)} 条提醒："
    result["reminders"] = []
    for r in reminders:
        full_prompt, runnable, status = compose_prompt(r["module"])
        entry = {
            "module": r["module"],
            "trigger_name": MODULES[r["module"]]["trigger_name"],
            "description": MODULES[r["module"]]["description"],
            "reason": r["reason"],
            "action": r["action"],
            "status": status,
            "runnable": runnable,
        }
        if runnable:
            entry["prompt_byte_length"] = len(full_prompt.encode("utf-8"))
            entry["prompt_preview"] = full_prompt[:150].replace("\n", " ") + "..."
            if args.show_prompt:
                entry["prompt_full"] = full_prompt
        result["reminders"].append(entry)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
