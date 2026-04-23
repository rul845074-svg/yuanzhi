#!/usr/bin/env python3
from __future__ import annotations

import calendar
import hashlib
import importlib.util
import json
import subprocess
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
# 本地 override 优先：config/agent.config.local.json 存在则用它（含真实 vault 路径），
# 不存在则用 config/agent.config.json（模板，用于 git 提交）
_LOCAL_CONFIG = WORKSPACE_ROOT / "config" / "agent.config.local.json"
_DEFAULT_CONFIG = WORKSPACE_ROOT / "config" / "agent.config.json"
CONFIG_PATH = _LOCAL_CONFIG if _LOCAL_CONFIG.exists() else _DEFAULT_CONFIG
GENERATOR_PATH = Path(__file__).resolve().with_name("generate_cognitive_workbench_data.py")
RUNTIME_OUTPUT = WORKSPACE_ROOT / "data" / "generated" / "cognitive-agent-runtime.json"
RUNS_DIR = WORKSPACE_ROOT / "data" / "generated" / "agent-runs"
PROGRESS_FILE = WORKSPACE_ROOT / "data" / "generated" / "agent-progress.json"
WORKBENCH_JSON = WORKSPACE_ROOT / "data" / "generated" / "cognitive-workbench-data.json"


def now_local() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_generator_module():
    spec = importlib.util.spec_from_file_location("growth_console_data", GENERATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_scheduler_module():
    # 加载中文名脚本：工作流调度员.py（M9 提醒器）
    scheduler_path = Path(__file__).resolve().with_name("工作流调度员.py")
    spec = importlib.util.spec_from_file_location("workflow_scheduler", scheduler_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_frontend_scale_module():
    # 加载 generate_frontend_scale.py（前端规模快照生成器）
    scale_path = Path(__file__).resolve().with_name("generate_frontend_scale.py")
    spec = importlib.util.spec_from_file_location("frontend_scale", scale_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _refresh_mirror_scale() -> None:
    """任务跑完后自动触发 —— 规模快照失败不应让主任务报 fail。stdout 捕获丢弃避免污染服务日志。"""
    import contextlib
    import io
    try:
        mod = load_frontend_scale_module()
        with contextlib.redirect_stdout(io.StringIO()):
            mod.main()
    except Exception as exc:  # noqa: BLE001
        print(f"[mirror-scale refresh] warn: {exc}")


def task_registry() -> dict[str, dict[str, Any]]:
    config = load_config()
    tasks = config.get("tasks", {})
    registry: dict[str, dict[str, Any]] = {}
    for name, task in tasks.items():
        prompt_path = task.get("prompt_path")
        prompt_summary = ""
        if prompt_path:
            prompt_file = WORKSPACE_ROOT / prompt_path
            if prompt_file.exists():
                prompt_summary = summarize_prompt(prompt_file)
        registry[name] = {
            "name": name,
            "label": task.get("label", name),
            "description": task.get("description", ""),
            "prompt_path": prompt_path,
            "prompt_summary": prompt_summary,
            "output_type": task.get("output_type"),
            "page_key": task.get("page_key"),
        }
    return registry


def summarize_prompt(path: Path) -> str:
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
        if len(lines) >= 2:
            break
    return " ".join(lines)


def read_existing_runtime() -> dict[str, Any]:
    return load_json(
        RUNTIME_OUTPUT,
        {
            "updated_at": None,
            "profile": None,
            "available_tasks": list(task_registry().values()),
            "last_run": None,
            "recent_runs": [],
        },
    )


def count_report_types(report_index: dict[str, Any]) -> dict[str, int]:
    counts = Counter(item.get("type") for item in report_index.get("items", []))
    return {
        "daily": counts.get("daily", 0),
        "ten_day": counts.get("ten_day", 0),
        "monthly": counts.get("monthly", 0),
        "growth": counts.get("growth", 0),
    }


def count_reminder_statuses(reminders: dict[str, Any]) -> dict[str, int]:
    counts = Counter(item.get("status") for item in reminders.get("items", []))
    return {
        "new": counts.get("new", 0),
        "active": counts.get("active", 0),
        "done": counts.get("done", 0),
        "snoozed": counts.get("snoozed", 0),
        "dismissed": counts.get("dismissed", 0),
    }


def resolve_paths(profile: str | None = None) -> dict[str, Path]:
    generator = load_generator_module()
    config = generator.load_config(profile)
    return config.paths


def make_snapshot(task_name: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str, list[str]]:
    pages = payload["pages"]
    report_counts = count_report_types(payload["report_index"])
    reminder_counts = count_reminder_statuses(payload.get("reminders", {"items": []}))
    home = pages["home"]

    if task_name == "daily_analysis":
        daily = pages["daily_report"]
        snapshot = {
            "page_type": daily["page_type"],
            "title": daily.get("title"),
            "date": daily.get("date"),
            "summary": daily.get("summary"),
            "season_window": daily.get("season_window"),
            "action_count": len(daily.get("daily_actions", [])),
            "term_count": len(daily.get("term_heatmap", [])),
        }
        summary = (
            f"已刷新最新日报《{daily.get('title') or '未命名日报'}》，"
            f"提取 {snapshot['action_count']} 条行动建议，"
            f"{snapshot['term_count']} 个术语热度词。"
        )
        inputs = [
            payload["state"]["meta"].get("latest_daily_report"),
            payload["artifact_paths"]["cognitive_state"],
        ]
        return snapshot, summary, [item for item in inputs if item]

    if task_name == "ten_day_summary":
        report = pages["tenday_report"]
        snapshot = {
            "page_type": report["page_type"],
            "title": report.get("title"),
            "range": report.get("range"),
            "summary": report.get("summary"),
            "phase_count": len(report.get("phase_segments", [])),
            "tracking_pattern_count": len(report.get("tracking_patterns", [])),
        }
        summary = (
            f"已刷新最新十日报《{report.get('title') or '未命名阶段报告'}》，"
            f"当前包含 {snapshot['phase_count']} 个阶段段落、"
            f"{snapshot['tracking_pattern_count']} 个追踪模式。"
        )
        inputs = [
            payload["state"]["meta"].get("latest_ten_day_report"),
            payload["artifact_paths"]["cognitive_state"],
        ]
        return snapshot, summary, [item for item in inputs if item]

    if task_name == "monthly_summary":
        report = pages["monthly_report"]
        snapshot = {
            "page_type": report["page_type"],
            "title": report.get("title"),
            "month": report.get("month"),
            "summary": report.get("summary"),
            "panorama_count": len(report.get("panorama_cards", [])),
            "open_topic_count": len(report.get("open_topics", [])),
        }
        summary = (
            f"已刷新最新月报《{report.get('title') or '未命名月报'}》，"
            f"沉淀 {snapshot['panorama_count']} 张全景卡片，"
            f"{snapshot['open_topic_count']} 条待跟进主题。"
        )
        inputs = [
            payload["state"]["meta"].get("latest_monthly_report"),
            payload["artifact_paths"]["cognitive_state"],
        ]
        return snapshot, summary, [item for item in inputs if item]

    if task_name == "growth_report_update":
        snapshot = {
            "page_type": home["page_type"],
            "pattern_count": len(home.get("patterns", [])),
            "belief_count": len(home.get("belief_migrations", [])),
            "capability_count": len(home.get("capabilities", [])),
            "mechanism_count": len(home.get("verified_mechanisms", [])),
            "identity_narrative": home.get("identity_narrative"),
        }
        summary = (
            f"已刷新首页/成长总览视图："
            f"{snapshot['pattern_count']} 个模式、"
            f"{snapshot['belief_count']} 条信念迁移、"
            f"{snapshot['capability_count']} 个能力维度。"
        )
        inputs = [
            payload["state"]["meta"].get("latest_growth_report"),
            payload["state"]["meta"].get("latest_monthly_report"),
            payload["artifact_paths"]["cognitive_state"],
        ]
        return snapshot, summary, [item for item in inputs if item]

    if task_name == "index_builder":
        snapshot = {
            "report_counts": report_counts,
            "report_index_items": len(payload["report_index"].get("items", [])),
            "suggestion_index_items": len(payload.get("suggestion_index", {}).get("items", [])),
            "pattern_count": payload["state"]["metrics"].get("pattern_count", 0),
            "warning_count": len(payload.get("warnings", [])),
        }
        summary = (
            f"已重建索引和状态文件："
            f"{snapshot['report_index_items']} 篇报告进入索引，"
            f"{snapshot['suggestion_index_items']} 条建议进入建议索引。"
        )
        inputs = [
            payload["artifact_paths"]["cognitive_state"],
            payload["artifact_paths"]["report_index"],
            payload["artifact_paths"]["suggestion_index"],
        ]
        return snapshot, summary, inputs

    if task_name == "reminder_manager":
        snapshot = {
            "reminder_count": len(payload.get("reminders", {}).get("items", [])),
            "suggestion_count": len(payload.get("suggestion_index", {}).get("items", [])),
            "active_count": reminder_counts["active"],
            "new_count": reminder_counts["new"],
            "home_visible_count": len(home.get("active_reminders", [])),
        }
        summary = (
            f"已更新提醒层："
            f"{snapshot['reminder_count']} 条提醒，"
            f"其中 active={snapshot['active_count']}，new={snapshot['new_count']}。"
        )
        inputs = [
            payload["artifact_paths"]["reminders"],
            payload["artifact_paths"]["suggestion_index"],
        ]
        return snapshot, summary, inputs

    raise ValueError(f"Unsupported task: {task_name}")


# ---------------------------------------------------------------------------
# Claude CLI task execution (daily_analysis_report / daily_analysis_state)
# ---------------------------------------------------------------------------

CLAUDE_TASKS = {
    "daily_analysis_report",
    "daily_analysis_state",
    "ten_day_summary",
    "monthly_summary",
    "life_growth_report",
    "next_month_astrology",
    "weekly_material_five",
    "monthly_knowledge_graph",
}

# 所有模块 prompt 已就绪，暂无 pending
PENDING_CLAUDE_TASKS: dict[str, str] = {}


def _update_progress(step: int, total: int, label: str, status: str = "running") -> None:
    payload = {
        "step": step,
        "total": total,
        "label": label,
        "status": status,
        "updated_at": now_local().isoformat(timespec="seconds"),
    }
    write_json(PROGRESS_FILE, payload)


def get_progress() -> dict[str, Any]:
    return load_json(PROGRESS_FILE, {"step": 0, "total": 0, "label": "", "status": "idle"})


def _vault_root(profile: str | None = None) -> Path:
    config = load_config()
    prof = profile or config.get("default_profile", "dev")
    root = config["profiles"][prof]["vault_root"]
    return Path(root).expanduser()


def _find_today_journal(vault: Path, date_str: str | None = None) -> Path:
    """Locate today's journal file. Checks top-level first, then month subdirs."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    journal_dir = vault / "时间轴" / "日志"
    # Top-level (recent files)
    candidate = journal_dir / f"{date_str}.md"
    if candidate.exists():
        return candidate
    # Month subdirs like 26-4/
    year_short = date_str[2:4]  # "26" from "2026-..."
    month = str(int(date_str[5:7]))  # "4" from "...-04-..."
    subdir = journal_dir / f"{year_short}-{month}"
    candidate = subdir / f"{date_str}.md"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"日志文件不存在: {date_str}.md (searched {journal_dir} and {subdir})")


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _read_prompt_template(task_name: str) -> str:
    config = load_config()
    task = config["tasks"][task_name]
    prompt_path = WORKSPACE_ROOT / task["prompt_path"]
    return prompt_path.read_text(encoding="utf-8")


def _load_existing_state(vault: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Load existing beliefs, patterns, reminders, concept_index for dedup."""
    paths = config.get("paths", {})

    def _read(key: str) -> Any:
        rel = paths.get(key)
        if not rel:
            return {}
        p = vault / rel
        return load_json(p, {})

    # Extract just the beliefs/patterns subtree (drop meta, metrics, identity_narrative, emotional_baseline — not needed for dedup)
    cogstate = _read("cognitive_state")
    beliefs = cogstate.get("beliefs", {}) if isinstance(cogstate, dict) else {}
    patterns = cogstate.get("patterns", {}) if isinstance(cogstate, dict) else {}

    return {
        "beliefs": beliefs,
        "patterns": patterns,
        "reminders": _read("reminders"),
        "concept_index": _read("concept_index"),
        "concept_candidates": _read("concept_candidates"),
    }


def _find_monthly_summary(vault: Path, date_str: str | None = None) -> str | None:
    """Return last month's summary (daily reports never read current-month, which is generated month-end)."""
    summary_dir = vault / "可实现" / "关于自己" / "月度汇总"
    if not summary_dir.exists():
        return None
    if date_str:
        y, m = int(date_str[:4]), int(date_str[5:7])
        ly, lm = (y - 1, 12) if m == 1 else (y, m - 1)
        candidate = summary_dir / f"{ly}_{lm:02d}_月度汇总.md"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    summaries = sorted(summary_dir.glob("*_月度汇总.md"), reverse=True)
    if summaries:
        return summaries[0].read_text(encoding="utf-8")
    return None


def _build_claude_prompt(task_name: str, journal_text: str, existing_state: dict[str, Any] | None = None, date_str: str | None = None, vault: Path | None = None, profile: str | None = None) -> str:
    template = _read_prompt_template(task_name)
    date_header = f"\n\n日期：{date_str}\n" if date_str else ""

    # M10 方法论前缀注入：M1 daily_analysis_report 走 narrative 产出，和 M2-M8 一样需要前缀
    # daily_analysis_state 是 JSON 提取器（要求只输出 JSON），不注入前缀避免污染输出纯净性
    prefix_block = ""
    if task_name == "daily_analysis_report":
        prefix_path = WORKSPACE_ROOT / "prompts" / "_方法论前缀.md"
        if prefix_path.exists():
            prefix_block = prefix_path.read_text(encoding="utf-8").strip() + "\n\n---\n\n"

    # Inject category lists + recent dimension usage (report task only)
    if task_name == "daily_analysis_report":
        try:
            from dimension_usage import format_recent_for_prompt, format_category_list_for_prompt
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from dimension_usage import format_recent_for_prompt, format_category_list_for_prompt
        for dim in ("psy", "meta", "phy"):
            template = template.replace(f"{{{{CATEGORY_LIST_{dim.upper()}}}}}", format_category_list_for_prompt(dim))
        recent_block = format_recent_for_prompt(profile=profile, days=7, before_date=date_str)
        template = template.replace("{{RECENT_DIMENSIONS}}", recent_block)

    # Inject monthly summary for context (report task only)
    context_section = ""
    if vault and task_name == "daily_analysis_report":
        monthly = _find_monthly_summary(vault, date_str)
        if monthly:
            context_section = f"\n\n---\n\n## 上下文：上月月度汇总（用于连续性分析）\n\n{monthly}"

    parts = [prefix_block, template, date_header, context_section, "\n---\n\n## 当日日志原文\n\n", journal_text]
    if task_name == "daily_analysis_state" and existing_state:
        parts.append("\n\n---\n\n## 已有状态（用于去重）\n\n```json\n")
        parts.append(json.dumps(existing_state, ensure_ascii=False, indent=2))
        parts.append("\n```\n")
    return "".join(parts)


def _call_claude_cli(prompt: str, output_json: bool = False) -> str:
    cmd = ["claude", "-p", prompt]
    if output_json:
        cmd.extend(["--output-format", "json"])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {result.stderr[:500]}")
    return result.stdout


def _update_concept_index(vault: Path, config: dict[str, Any], updates: list[dict[str, Any]]) -> None:
    rel = config["paths"]["concept_index"]
    path = vault / rel
    index = load_json(path, {"concepts": {}})
    concepts = index.setdefault("concepts", {})
    for entry in updates:
        name = entry["concept_name"]
        seen_in = entry.get("seen_in", "")
        if name in concepts:
            seen_list = concepts[name].setdefault("seen_in", [])
            if seen_in and seen_in not in seen_list:
                seen_list.append(seen_in)
        else:
            concepts[name] = {"first_seen": seen_in, "seen_in": [seen_in] if seen_in else []}
    index["updated_at"] = now_local().isoformat(timespec="seconds")
    write_json(path, index)


def _update_concept_candidates(vault: Path, config: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    rel = config["paths"]["concept_candidates"]
    path = vault / rel
    existing = load_json(path, {"candidates": []})
    existing_names = {c["concept_name"] for c in existing.get("candidates", [])}
    for c in candidates:
        if c["concept_name"] not in existing_names:
            existing["candidates"].append({
                "id": f"c_{c['concept_name']}_{c.get('first_seen', '')}".replace("-", ""),
                "concept_name": c["concept_name"],
                "first_seen": c.get("first_seen", ""),
                "seen_in": [c.get("first_seen", "")],
                "times_seen": 1,
                "status": "new",
                "context_summary": c.get("context_summary", ""),
                "reviewed_at": None,
            })
            existing_names.add(c["concept_name"])
        else:
            # Update seen count
            for ec in existing["candidates"]:
                if ec["concept_name"] == c["concept_name"]:
                    seen_date = c.get("first_seen", "")
                    if seen_date and seen_date not in ec.get("seen_in", []):
                        ec.setdefault("seen_in", []).append(seen_date)
                        ec["times_seen"] = len(ec["seen_in"])
                    break
    existing["updated_at"] = now_local().isoformat(timespec="seconds")
    write_json(path, existing)


# ---------------------------------------------------------------------------
# M2 十日报告辅助函数
# ---------------------------------------------------------------------------

def _get_ten_day_window(date_str: str) -> tuple[str, str]:
    """给定窗口末日（必须是 10/20/30），返回 (窗口首日, 窗口末日) ISO 字符串。
    窗口首日 = 末日 - 9 天。31 号的日志不归十日报（由 M3 月汇总带）。"""
    end_d = datetime.strptime(date_str, "%Y-%m-%d").date()
    if end_d.day not in (10, 20, 30):
        raise ValueError(f"十日窗口末日必须是 10/20/30，收到 {date_str}")
    start_d = end_d - timedelta(days=9)
    if start_d.month != end_d.month or start_d.day not in (1, 11, 21):
        raise ValueError(f"十日窗口异常：{date_str} → 首日 {start_d}")
    return start_d.isoformat(), end_d.isoformat()


def _compute_compare_dates(window_start_str: str, window_end_str: str) -> tuple[str, str, bool]:
    """能力对比表左右列日期 + 是否需要读上期。
    月内第 1 个十日（首日 1 号）→ 左列 = 窗口首日，不读上期；
    月内第 2/3 个十日（首日 11/21 号）→ 左列 = 上期末日（首日 - 1），读上期。
    右列永远 = 窗口末日。月间衔接由 M3 负责，不跨月读。"""
    start_d = datetime.strptime(window_start_str, "%Y-%m-%d").date()
    if start_d.day == 1:
        return window_start_str, window_end_str, False
    left = start_d - timedelta(days=1)
    return left.isoformat(), window_end_str, True


def _read_daily_reports_in_window(vault: Path, start_str: str, end_str: str, paths: dict[str, Any]) -> tuple[str, int]:
    """读窗口内全部日报，返回 (拼接文本, 实际找到的篇数)。"""
    rel = paths.get("daily_reports", "可实现/关于自己/每日报告")
    report_dir = vault / rel
    start_d = datetime.strptime(start_str, "%Y-%m-%d").date()
    end_d = datetime.strptime(end_str, "%Y-%m-%d").date()
    chunks: list[str] = []
    count = 0
    cur = start_d
    while cur <= end_d:
        fname = f"{cur.year}_{cur.month:02d}_{cur.day:02d}_日志整理与分析.md"
        p = report_dir / fname
        if p.exists():
            chunks.append(f"\n\n### 【{cur.isoformat()}】日报\n\n{p.read_text(encoding='utf-8')}")
            count += 1
        cur += timedelta(days=1)
    return "".join(chunks), count


def _find_prev_ten_day_report(vault: Path, window_start_str: str, paths: dict[str, Any]) -> str | None:
    """月内第 2/3 个十日——找同月上期十日报。只用于能力对比表左列，不跨月。"""
    rel = paths.get("ten_day_reports", "可实现/关于自己/十日总报告")
    report_dir = vault / rel
    start_d = datetime.strptime(window_start_str, "%Y-%m-%d").date()
    if start_d.day == 11:
        prev_start, prev_end = 1, 10
    elif start_d.day == 21:
        prev_start, prev_end = 11, 20
    else:
        return None
    fname = f"{start_d.year}_{start_d.month:02d}_{prev_start:02d}_to_{prev_end:02d}.md"
    p = report_dir / fname
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def _build_ten_day_prompt(template: str, daily_reports_text: str, prev_ten_day_text: str | None,
                           left_date: str, right_date: str) -> str:
    """拼接 M10 方法论前缀 + 模块 prompt（替换占位符）+ 10 篇日报 + 条件性上期十日报。"""
    prefix_path = WORKSPACE_ROOT / "prompts" / "_方法论前缀.md"
    prefix = prefix_path.read_text(encoding="utf-8") if prefix_path.exists() else ""
    body = template.replace("{{COMPARE_LEFT_DATE}}", left_date)
    body = body.replace("{{COMPARE_RIGHT_DATE}}", right_date)
    parts: list[str] = []
    if prefix:
        parts.append(prefix)
        parts.append("\n\n---\n\n# 模块专属 prompt · M2_十日报告\n\n")
    parts.append(body)
    parts.append("\n\n---\n\n## 输入资源 1 · 本十日 10 篇日报（主输入）\n")
    parts.append(daily_reports_text)
    if prev_ten_day_text:
        parts.append("\n\n---\n\n## 输入资源 2 · 上期十日报（仅用于能力对比表左列参照）\n\n")
        parts.append(prev_ten_day_text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# M3 月度汇总辅助函数
# ---------------------------------------------------------------------------

def _verify_last_day_of_month(date_str: str) -> tuple[int, int]:
    """M3 必须在月最后一天触发。返回 (year, month)。"""
    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    last = calendar.monthrange(d.year, d.month)[1]
    if d.day != last:
        raise ValueError(f"monthly_summary 必须在月最后一天触发，收到 {date_str}（该月最后一天是 {d.year}-{d.month:02d}-{last:02d}）")
    return d.year, d.month


def _read_ten_day_reports_in_month(vault: Path, year: int, month: int, paths: dict[str, Any]) -> tuple[str, int]:
    """读本月已有的十日报告（1-10 / 11-20 / 21-30）。2 月没有 21-30，只会读到 2 个。"""
    rel = paths.get("ten_day_reports", "可实现/关于自己/十日总报告")
    report_dir = vault / rel
    chunks: list[str] = []
    count = 0
    for start_day, end_day in [(1, 10), (11, 20), (21, 30)]:
        fname = f"{year}_{month:02d}_{start_day:02d}_to_{end_day:02d}.md"
        p = report_dir / fname
        if p.exists():
            chunks.append(
                f"\n\n### 【{year}-{month:02d}-{start_day:02d} ~ {year}-{month:02d}-{end_day:02d}】十日报告\n\n"
                + p.read_text(encoding="utf-8")
            )
            count += 1
    return "".join(chunks), count


def _find_prev_month_summary(vault: Path, year: int, month: int, paths: dict[str, Any]) -> str | None:
    """读上月月度汇总（跨年 1 月 → 上年 12 月）。"""
    rel = paths.get("monthly_reports", "可实现/关于自己/月度汇总")
    summary_dir = vault / rel
    ly, lm = (year - 1, 12) if month == 1 else (year, month - 1)
    p = summary_dir / f"{ly}_{lm:02d}_月度汇总.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def _build_monthly_prompt(template: str, ten_day_text: str, prev_month_text: str | None,
                          year: int, month: int) -> str:
    """拼接 M10 方法论前缀 + M3 模块 prompt（替换占位符）+ 本月 2-3 个十日报告 + 上月月汇总。"""
    prefix_path = WORKSPACE_ROOT / "prompts" / "_方法论前缀.md"
    prefix = prefix_path.read_text(encoding="utf-8") if prefix_path.exists() else ""

    last_day = calendar.monthrange(year, month)[1]
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    replacements = {
        "{{YEAR}}": str(year),
        "{{MONTH}}": f"{month:02d}",
        "{{MONTH_DISPLAY}}": str(month),
        "{{MONTH_LABEL}}": f"{year}-{month:02d}",
        "{{PREV_MONTH_LABEL}}": f"{prev_y}-{prev_m:02d}",
        "{{LAST_DAY}}": f"{last_day:02d}",
    }
    body = template
    for placeholder, value in replacements.items():
        body = body.replace(placeholder, value)

    parts: list[str] = []
    if prefix:
        parts.append(prefix)
        parts.append("\n\n---\n\n# 模块专属 prompt · M3_月度汇总\n\n")
    parts.append(body)
    parts.append(f"\n\n---\n\n## 本月信息\n\n当前月：**{year}-{month:02d}**（覆盖到当月最后一天 {year}-{month:02d}-{last_day:02d}）\n")
    parts.append("\n\n---\n\n## 输入资源 1 · 本月十日报告（主输入）\n")
    parts.append(ten_day_text)
    if prev_month_text:
        parts.append(f"\n\n---\n\n## 输入资源 2 · 上月（{prev_y}-{prev_m:02d}）月度汇总（用于连续性对比）\n\n")
        parts.append(prev_month_text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# M4 人生成长报告辅助函数
# ---------------------------------------------------------------------------

def _growth_report_path(vault: Path, config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get("growth_report", "核心/人生轨迹总览.md")
    return vault / rel


def _read_prev_growth_report(vault: Path, config: dict[str, Any]) -> tuple[str, str | None]:
    """读上版人生轨迹总览。返回 (全文, 上版最后更新日期或 None)。
    从头部 `> 最后更新：YYYY-MM-DD` 行解析日期。"""
    path = _growth_report_path(vault, config)
    if not path.exists():
        return "", None
    text = path.read_text(encoding="utf-8")
    prev_date: str | None = None
    for line in text.splitlines()[:20]:
        m = line.strip()
        if m.startswith("> 最后更新：") or m.startswith(">最后更新："):
            # 可能是 "> 最后更新：2026-03-31" 或 "> 最后更新：2026-03-31（...）"
            after = m.split("：", 1)[1].strip() if "：" in m else ""
            # 截取前 10 位 YYYY-MM-DD（若符合）
            candidate = after[:10]
            if len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
                prev_date = candidate
            break
    return text, prev_date


def _read_current_month_summary(vault: Path, year: int, month: int, config: dict[str, Any]) -> str | None:
    """M4 读本月（year-month）月汇总。与 M3 读上月的 _find_prev_month_summary 区别：这里是当月。"""
    rel = config.get("paths", {}).get("monthly_reports", "可实现/关于自己/月度汇总")
    summary_dir = vault / rel
    p = summary_dir / f"{year}_{month:02d}_月度汇总.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


def _build_life_growth_prompt(template: str, prev_growth_text: str, month_summary_text: str,
                               year: int, month: int, prev_version_date: str | None) -> str:
    """拼接 M10 方法论前缀 + M4 模块 prompt（替换占位符）+ 上版总览 + 本月月汇总。"""
    prefix_path = WORKSPACE_ROOT / "prompts" / "_方法论前缀.md"
    prefix = prefix_path.read_text(encoding="utf-8") if prefix_path.exists() else ""

    last_day = calendar.monthrange(year, month)[1]
    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    replacements = {
        "{{YEAR}}": str(year),
        "{{MONTH}}": f"{month:02d}",
        "{{MONTH_DISPLAY}}": str(month),
        "{{MONTH_LABEL}}": f"{year}-{month:02d}",
        "{{LAST_DAY}}": f"{last_day:02d}",
        "{{NEXT_MONTH_DISPLAY}}": str(next_m),
        "{{PREV_VERSION_DATE}}": prev_version_date or "（上版无标注日期）",
    }
    body = template
    for placeholder, value in replacements.items():
        body = body.replace(placeholder, value)

    parts: list[str] = []
    if prefix:
        parts.append(prefix)
        parts.append("\n\n---\n\n# 模块专属 prompt · M4_人生成长报告\n\n")
    parts.append(body)
    parts.append(
        f"\n\n---\n\n## 本次更新信息\n\n"
        f"当前月：**{year}-{month:02d}**（覆盖到 {year}-{month:02d}-{last_day:02d}）\n"
        f"上版最后更新：**{prev_version_date or '未知'}**\n"
        f"下月预告填入：{year}年{next_m}月末\n"
    )
    parts.append("\n\n---\n\n## 输入资源 1 · 上版人生轨迹总览（必读主输入，旧内容一字不动保留）\n\n")
    parts.append(prev_growth_text if prev_growth_text else "（空——首次跑，请按第六节板块结构起草基线版）")
    parts.append(f"\n\n---\n\n## 输入资源 2 · 本月（{year}-{month:02d}）月度汇总（必读，用于筛塑造性新增）\n\n")
    parts.append(month_summary_text)
    return "".join(parts)


# ---------------------------------------------------------------------------
# M8 下月星象辅助函数
# ---------------------------------------------------------------------------

ASTROLOGY_SECTION_HEADER_PREFIX = "## 十、下月星象参考"


def _monthly_report_path(vault: Path, year: int, month: int, config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get("monthly_reports", "可实现/关于自己/月度汇总")
    return vault / rel / f"{year}_{month:02d}_月度汇总.md"


def _extract_astrology_section(monthly_text: str) -> tuple[str, str]:
    """从月报全文里切出 (前 9 节正文, 第十节起的全部内容)。
    如果找不到第十节——返回 (原文, '')。"""
    idx = monthly_text.find(ASTROLOGY_SECTION_HEADER_PREFIX)
    if idx < 0:
        return monthly_text, ""
    return monthly_text[:idx].rstrip(), monthly_text[idx:]


def _build_astrology_prompt(template: str, current_month_main: str, prev_astrology_section: str,
                             year: int, month: int) -> str:
    """拼接 M10 方法论前缀 + M8 模块 prompt（替换占位符）+ 上月预测板块 + 本月月汇总前 9 节。"""
    prefix_path = WORKSPACE_ROOT / "prompts" / "_方法论前缀.md"
    prefix = prefix_path.read_text(encoding="utf-8") if prefix_path.exists() else ""

    next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    replacements = {
        "{{CURRENT_YEAR_MONTH}}": f"{year}-{month:02d}",
        "{{CURRENT_YEAR_MONTH_UNDERSCORE}}": f"{year}_{month:02d}",
        "{{CURRENT_MONTH_DISPLAY}}": str(month),
        "{{NEXT_YEAR_MONTH}}": f"{next_y}-{next_m:02d}",
        "{{NEXT_MONTH_DISPLAY}}": str(next_m),
        "{{PREV_MONTH_LABEL}}": f"{prev_y}-{prev_m:02d}",
        "{{PREV_MONTH_LABEL_UNDERSCORE}}": f"{prev_y}_{prev_m:02d}",
    }
    body = template
    for placeholder, value in replacements.items():
        body = body.replace(placeholder, value)

    parts: list[str] = []
    if prefix:
        parts.append(prefix)
        parts.append("\n\n---\n\n# 模块专属 prompt · M8_下月星象\n\n")
    parts.append(body)
    parts.append(
        f"\n\n---\n\n## 本次运行信息\n\n"
        f"本月：**{year}-{month:02d}**（完成到 {year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}）\n"
        f"上月：**{prev_y}-{prev_m:02d}**\n"
        f"下月：**{next_y}-{next_m:02d}**（本次要预测的目标月）\n"
    )
    parts.append("\n\n---\n\n## 输入资源 1 · 上月月报末尾的「对本月星象预测」板块（当初预测，用于信用校准）\n\n")
    if prev_astrology_section:
        parts.append(prev_astrology_section)
    else:
        parts.append(f"（上月 {prev_y}-{prev_m:02d} 月报不存在或没有第十节——本月 M8 是首次跑，10.1 节请写「首次跑，本月无上月预测可回顾」）")
    parts.append(f"\n\n---\n\n## 输入资源 2 · 本月（{year}-{month:02d}）月度汇总前 9 节（本月实际发生的精华）\n\n")
    parts.append(current_month_main)
    return "".join(parts)


# ---------------------------------------------------------------------------
# M5a 素材库五件套（周度）辅助函数
# ---------------------------------------------------------------------------

MATERIAL_LIBRARY_FILES = (
    "素材库_金句集.md",
    "素材库_主题线索.md",
    "素材库_场景片段.md",
    "素材库_原创洞察.md",
    "素材库_思维差异.md",
)


def _material_library_dir(vault: Path, config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get("material_library", "可实现/素材库")
    return vault / rel


def _get_week_bounds(sunday_date: date) -> tuple[date, date]:
    if sunday_date.weekday() != 6:
        raise ValueError(f"weekly_material_five 要求 date 是周日 (weekday=6)，收到 {sunday_date} (weekday={sunday_date.weekday()})")
    monday = sunday_date - timedelta(days=6)
    return monday, sunday_date


def _read_weekly_daily_reports(vault: Path, monday: date, sunday: date, paths: dict[str, Any]) -> tuple[str, int]:
    rel = paths.get("daily_reports", "可实现/关于自己/每日报告")
    report_dir = vault / rel
    chunks: list[str] = []
    count = 0
    cur = monday
    while cur <= sunday:
        fname = f"{cur.year}_{cur.month:02d}_{cur.day:02d}_日志整理与分析.md"
        p = report_dir / fname
        if p.exists():
            weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][cur.weekday()]
            chunks.append(f"\n\n### 【{cur.isoformat()} · {weekday_cn}】日报\n\n{p.read_text(encoding='utf-8')}")
            count += 1
        cur += timedelta(days=1)
    return "".join(chunks), count


def _read_material_skeletons(material_dir: Path) -> str:
    chunks: list[str] = []
    for fname in MATERIAL_LIBRARY_FILES:
        p = material_dir / fname
        if not p.exists():
            chunks.append(f"\n### 骨架 · {fname}\n\n（文件不存在——本周如果要写入会自动创建）")
            continue
        lines = p.read_text(encoding="utf-8").splitlines()
        skeleton_lines = [
            ln for ln in lines
            if ln.lstrip().startswith("#") and not ln.lstrip().startswith("####")
        ]
        chunks.append(f"\n### 骨架 · {fname}\n\n" + "\n".join(skeleton_lines))
    return "\n".join(chunks)


def _next_diff_index(material_dir: Path) -> str:
    p = material_dir / "素材库_思维差异.md"
    if not p.exists():
        return "001"
    import re as _re
    text = p.read_text(encoding="utf-8")
    nums = [int(m.group(1)) for m in _re.finditer(r"###\s*(\d{3})\s*[｜|]", text)]
    if not nums:
        return "001"
    return f"{max(nums) + 1:03d}"


def _week_idx_in_month(sunday: date) -> str:
    first = date(sunday.year, sunday.month, 1)
    days_to_first_sunday = (6 - first.weekday()) % 7
    first_sunday = first + timedelta(days=days_to_first_sunday)
    idx = (sunday - first_sunday).days // 7 + 1
    return f"W{idx}"


def _build_weekly_material_prompt(template: str, daily_reports_text: str, skeleton_text: str,
                                   monday: date, sunday: date, next_diff_idx: str) -> str:
    prefix_path = WORKSPACE_ROOT / "prompts" / "_方法论前缀.md"
    prefix = prefix_path.read_text(encoding="utf-8") if prefix_path.exists() else ""

    replacements = {
        "{{WEEK_START}}": monday.isoformat(),
        "{{WEEK_END}}": sunday.isoformat(),
        "{{CURRENT_YEAR_MONTH}}": f"{sunday.year}-{sunday.month:02d}",
        "{{CURRENT_MONTH_CN}}": f"{sunday.month}月",
        "{{WEEK_IDX_IN_MONTH}}": _week_idx_in_month(sunday),
        "{{NEXT_DIFF_INDEX}}": next_diff_idx,
    }
    body = template
    for placeholder, value in replacements.items():
        body = body.replace(placeholder, value)

    parts: list[str] = []
    if prefix:
        parts.append(prefix)
        parts.append("\n\n---\n\n# 模块专属 prompt · M5a_素材库五件套\n\n")
    parts.append(body)
    parts.append(
        f"\n\n---\n\n## 本次运行信息\n\n"
        f"本周：**{monday.isoformat()}（周一）~ {sunday.isoformat()}（周日）**\n"
        f"本周在本月序号：**{_week_idx_in_month(sunday)}**\n"
        f"思维差异库下一可用流水号：**{next_diff_idx}**\n"
    )
    parts.append("\n---\n\n## 输入资源 1 · 本周日报拼接（主输入）\n")
    parts.append(daily_reports_text)
    parts.append("\n\n---\n\n## 各文件当前章节骨架（只含 H1-H3 标题行，用于判断追加位置）\n")
    parts.append(skeleton_text)
    return "".join(parts)


def _parse_weekly_material_segments(output: str) -> list[dict[str, str]]:
    """按 <!-- FILE: ... --> ... <!-- END_FILE --> 把 LLM 输出切成分段列表。"""
    import re as _re
    pattern = _re.compile(
        r"<!--\s*FILE:\s*([^;]+?)\s*;\s*ANCHOR:\s*(.+?)\s*;\s*MODE:\s*(\w+)\s*-->"
        r"(.*?)"
        r"<!--\s*END_FILE\s*-->",
        _re.DOTALL,
    )
    segments: list[dict[str, str]] = []
    for m in pattern.finditer(output):
        body = m.group(4).strip()
        if not body:
            continue
        segments.append({
            "file": m.group(1).strip(),
            "anchor": m.group(2).strip(),
            "mode": m.group(3).strip(),
            "body": body,
        })
    return segments


def _apply_segment_to_file(file_path: Path, anchor: str, mode: str, body: str) -> None:
    """按 mode 把 body 合并到 file_path。
    - append_to_end：直接追加到文件末尾
    - append_under_anchor：找 anchor 行，插到该章节末尾（下一个同级或更高级标题前）
    - create_anchor_if_missing_then_append：anchor 存在则等同 append_under_anchor；否则文件末尾新建 anchor 再追加
    """
    if not file_path.exists():
        # 文件不存在：用素材库文件名作标题兜底创建
        header = f"# {file_path.stem.replace('素材库_', '')}\n\n"
        file_path.write_text(header + f"{anchor}\n\n{body}\n", encoding="utf-8")
        return

    text = file_path.read_text(encoding="utf-8")

    if mode == "append_to_end":
        new_text = text.rstrip() + f"\n\n{body}\n"
        file_path.write_text(new_text, encoding="utf-8")
        return

    if mode == "create_anchor_if_missing_then_append":
        if anchor.strip() in text:
            # anchor 已存在——降级为 append_under_anchor
            mode = "append_under_anchor"
        else:
            new_text = text.rstrip() + f"\n\n---\n\n{anchor}\n\n{body}\n"
            file_path.write_text(new_text, encoding="utf-8")
            return

    if mode == "append_under_anchor":
        def _heading_level(raw_line: str) -> int:
            stripped_line = raw_line.lstrip()
            if not stripped_line.startswith("#"):
                return 0
            return len(stripped_line) - len(stripped_line.lstrip("#"))

        lines = text.splitlines()
        anchor_idx = -1
        anchor_level = 0
        target = anchor.strip()
        for i, ln in enumerate(lines):
            if ln.strip() == target:
                anchor_idx = i
                anchor_level = _heading_level(ln)
                break
        if anchor_idx < 0:
            # anchor 找不到——回退到末尾追加并把 anchor 行一起带上，保证结构完整
            new_text = text.rstrip() + f"\n\n{anchor}\n\n{body}\n"
            file_path.write_text(new_text, encoding="utf-8")
            return
        insert_idx = len(lines)
        for j in range(anchor_idx + 1, len(lines)):
            level = _heading_level(lines[j])
            if level > 0 and level <= anchor_level:
                insert_idx = j
                break
        head = "\n".join(lines[:insert_idx]).rstrip()
        tail = "\n".join(lines[insert_idx:])
        new_text = head + f"\n\n{body}\n\n" + tail
        if not new_text.endswith("\n"):
            new_text += "\n"
        file_path.write_text(new_text, encoding="utf-8")
        return

    raise ValueError(f"未知的 M5a MODE: {mode}")


# ---------------------------------------------------------------------------
# M5b 月末知识图谱辅助函数
# ---------------------------------------------------------------------------

def _knowledge_graph_path(vault: Path, config: dict[str, Any]) -> Path:
    rel = config.get("paths", {}).get(
        "knowledge_graph",
        "可实现/素材库/知识图谱_物理×认知×心理.md",
    )
    return vault / rel


def _read_monthly_material_additions(vault: Path, year: int, month: int, config: dict[str, Any]) -> str:
    """聚合 5 个素材库文件里「## {月}月新增」段，作为知识图谱的本月素材底料。
    文件若无显式月份分档段（主题线索/场景片段/原创洞察/思维差异等），取文件尾部最多 3000 字节作兜底。
    """
    material_dir = _material_library_dir(vault, config)
    month_header = f"## {month}月新增"
    chunks: list[str] = []
    for fname in MATERIAL_LIBRARY_FILES:
        p = material_dir / fname
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        idx = text.find(month_header)
        if idx < 0:
            tail = text[-3000:] if len(text) > 3000 else text
            chunks.append(f"\n### {fname}（无显式月份分档段，取尾部最近 3000 字节）\n\n{tail}")
            continue
        sub = text[idx:]
        sub_lines = sub.splitlines()
        end = len(sub_lines)
        for j in range(1, len(sub_lines)):
            ln = sub_lines[j]
            if ln.startswith("## ") and not ln.startswith("### "):
                end = j
                break
        month_section = "\n".join(sub_lines[:end]).rstrip()
        chunks.append(f"\n### {fname}\n\n{month_section}")
    if not chunks:
        return f"（本月（{year}-{month:02d}）5 件套没有任何可读段——可能本月 M5a 未跑）"
    return "\n\n".join(chunks)


def _build_knowledge_graph_prompt(template: str, current_kg_text: str, monthly_additions: str,
                                   current_month_summary: str, year: int, month: int) -> str:
    prefix_path = WORKSPACE_ROOT / "prompts" / "_方法论前缀.md"
    prefix = prefix_path.read_text(encoding="utf-8") if prefix_path.exists() else ""

    prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
    replacements = {
        "{{CURRENT_YEAR_MONTH}}": f"{year}-{month:02d}",
        "{{CURRENT_YEAR_MONTH_UNDERSCORE}}": f"{year}_{month:02d}",
        "{{CURRENT_MONTH_CN}}": f"{month}月",
        "{{PREV_MONTH_LABEL_UNDERSCORE}}": f"{prev_y}_{prev_m:02d}",
    }
    body = template
    for placeholder, value in replacements.items():
        body = body.replace(placeholder, value)

    parts: list[str] = []
    if prefix:
        parts.append(prefix)
        parts.append("\n\n---\n\n# 模块专属 prompt · M5b_月末知识图谱\n\n")
    parts.append(body)
    parts.append(
        f"\n\n---\n\n## 本次运行信息\n\n"
        f"本月：**{year}-{month:02d}**（完成到 {year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}）\n"
    )
    parts.append("\n---\n\n## 输入 · 当前知识图谱全文（旧节点一字不动保留）\n\n")
    parts.append(
        current_kg_text
        if current_kg_text
        else "（空——首次跑，请按「物理 / 认知行为学 / 心理学」三象限起草基线版）"
    )
    parts.append(f"\n\n---\n\n## 输入 · 本月（{year}-{month:02d}）5 件套「{month}月新增」段\n")
    parts.append(monthly_additions)
    parts.append(f"\n\n---\n\n## 输入 · 本月（{year}-{month:02d}）月度汇总前 9 节\n\n")
    parts.append(current_month_summary)
    return "".join(parts)


def run_claude_task(task_name: str, profile: str | None = None, date_str: str | None = None) -> dict[str, Any]:
    """Run a Claude CLI-backed task (daily_analysis_report / daily_analysis_state / ten_day_summary / monthly_summary / life_growth_report / next_month_astrology)."""
    if task_name in PENDING_CLAUDE_TASKS:
        module_label = PENDING_CLAUDE_TASKS[task_name]
        raise ValueError(
            f"{module_label}（{task_name}）prompt 待建 —— Task #18 里程碑回填 "
            f"`prompts/{task_name}.md` 后，把 task_name 从 PENDING_CLAUDE_TASKS 搬到 CLAUDE_TASKS，"
            f"并在 run_claude_task() 里加对应分支即可激活。"
        )
    if task_name not in CLAUDE_TASKS:
        raise ValueError(f"Not a Claude CLI task: {task_name}")

    NON_DAILY_TASKS = (
        "ten_day_summary", "monthly_summary",
        "life_growth_report", "next_month_astrology",
        "weekly_material_five", "monthly_knowledge_graph",
    )
    total_steps = 6 if task_name in ("daily_analysis_report",) + NON_DAILY_TASKS else 5

    initial_label = "加载任务配置..." if task_name in NON_DAILY_TASKS else "读取上月月度汇总，获取上下文..."
    _update_progress(1, total_steps, initial_label)
    config = load_config()
    prof = profile or config.get("default_profile", "dev")
    vault = _vault_root(prof)

    # 非单日型任务（M2/M3/M4/M5a/M5b/M8）不读单日 journal——单独分支处理
    journal_hash: str | None = None
    journal_text: str = ""
    if task_name not in NON_DAILY_TASKS:
        _update_progress(2, total_steps, f"读取 {date_str or '今天'} 的日志...")
        journal_path = _find_today_journal(vault, date_str)
        journal_text = journal_path.read_text(encoding="utf-8")
        if not journal_text.strip():
            _update_progress(0, 0, "日志文件为空", status="error")
            raise ValueError(f"日志文件为空: {journal_path.name}，请先写日志再分析。")
        journal_hash = _file_hash(journal_path)

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    started_at = now_local()
    task_config = config["tasks"][task_name]

    if task_name == "daily_analysis_report":
        _update_progress(3, total_steps, "构建分析 prompt...")
        prompt = _build_claude_prompt(task_name, journal_text, date_str=date_str, vault=vault, profile=prof)

        _update_progress(4, total_steps, "Claude 正在生成分析报告...（这一步最慢，通常 1-2 分钟）")
        output = _call_claude_cli(prompt, output_json=False)

        _update_progress(5, total_steps, "保存报告到 Obsidian...")
        report_dir = vault / config["paths"]["daily_reports"]
        report_dir.mkdir(parents=True, exist_ok=True)
        date_underscored = date_str.replace("-", "_")
        report_path = report_dir / f"{date_underscored}_日志整理与分析.md"
        report_path.write_text(output, encoding="utf-8")

        # Upsert dimension usage entry for this report (parses the trailing HTML tag)
        try:
            from dimension_usage import update_from_report
            update_from_report(report_path, profile=prof)
        except Exception as exc:
            # 不因为 index 回写失败而阻断报告生成
            print(f"[dimension_usage] update failed: {exc}")

        _update_progress(6, total_steps, f"报告已保存: {report_path.name}", status="done")
        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "journal_date": date_str,
            "journal_hash": journal_hash,
            "output_path": str(report_path),
            "summary": f"已生成 {date_str} 的每日报告，写入 {report_path.name}",
        }

        # 【M2-4】日报跑完后，串调 M9 工作流调度员，提醒月末/十日/周日节点
        reminders: list[dict[str, Any]] = []
        try:
            scheduler = load_scheduler_module()
            from datetime import date as _date
            today_obj = _date.fromisoformat(date_str)
            reminders = scheduler.decide_reminders(today_obj)
            if reminders:
                print(f"\n顺便提醒你 {len(reminders)} 件事：")
                for r in reminders:
                    print(f"  · {r['module']}：{r['action']}")
        except Exception as exc:
            # 调度员失败不阻断日报生成
            print(f"[M9 调度员] 调用失败（不影响日报）: {exc}")
        result["reminders"] = reminders

        persist_run(result)
        return result

    if task_name == "ten_day_summary":
        if date_str is None:
            raise ValueError("ten_day_summary 需要指定 --date（窗口末日 YYYY-MM-DD，10/20/30）")
        _update_progress(2, total_steps, "计算十日窗口...")
        window_start, window_end = _get_ten_day_window(date_str)
        left_date, right_date, needs_prev = _compute_compare_dates(window_start, window_end)

        _update_progress(3, total_steps, f"读取 {window_start} ~ {window_end} 的日报...")
        daily_reports_text, report_count = _read_daily_reports_in_window(vault, window_start, window_end, config["paths"])
        if report_count == 0:
            _update_progress(0, 0, "窗口内无日报", status="error")
            raise ValueError(f"窗口 {window_start} ~ {window_end} 内没有找到任何日报，无法生成十日报告")

        prev_ten_day_text = _find_prev_ten_day_report(vault, window_start, config["paths"]) if needs_prev else None

        _update_progress(4, total_steps, "构建十日 prompt...")
        template = _read_prompt_template(task_name)
        prompt = _build_ten_day_prompt(template, daily_reports_text, prev_ten_day_text, left_date, right_date)

        _update_progress(5, total_steps, "Claude 正在生成十日报告...（通常 2-3 分钟）")
        output = _call_claude_cli(prompt, output_json=False)

        _update_progress(6, total_steps, "保存报告到 Obsidian...")
        report_dir = vault / config["paths"]["ten_day_reports"]
        report_dir.mkdir(parents=True, exist_ok=True)
        start_d = datetime.strptime(window_start, "%Y-%m-%d").date()
        end_d = datetime.strptime(window_end, "%Y-%m-%d").date()
        report_name = f"{start_d.year}_{start_d.month:02d}_{start_d.day:02d}_to_{end_d.day:02d}.md"
        report_path = report_dir / report_name
        report_path.write_text(output, encoding="utf-8")

        _update_progress(6, total_steps, f"十日报告已保存: {report_path.name}", status="done")
        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "window_start": window_start,
            "window_end": window_end,
            "daily_reports_count": report_count,
            "prev_ten_day_included": bool(prev_ten_day_text),
            "output_path": str(report_path),
            "summary": (
                f"已生成 {window_start} ~ {window_end} 的十日报告，"
                f"读入 {report_count}/10 篇日报"
                + ("（含上期十日报作左列参照）" if prev_ten_day_text else "")
                + f"，写入 {report_path.name}"
            ),
        }
        persist_run(result)
        return result

    if task_name == "monthly_summary":
        if date_str is None:
            raise ValueError("monthly_summary 需要指定 --date（该月最后一天 YYYY-MM-DD）")
        _update_progress(2, total_steps, "校验日期为月最后一天...")
        year, month = _verify_last_day_of_month(date_str)

        _update_progress(3, total_steps, f"读取 {year}-{month:02d} 的十日报告 + 上月月汇总...")
        ten_day_text, ten_day_count = _read_ten_day_reports_in_month(vault, year, month, config["paths"])
        if ten_day_count == 0:
            _update_progress(0, 0, "本月无十日报告", status="error")
            raise ValueError(f"{year}-{month:02d} 月内没找到任何十日报告，月度汇总没法生成——先补齐十日报告")
        prev_month_text = _find_prev_month_summary(vault, year, month, config["paths"])

        _update_progress(4, total_steps, "构建月度 prompt...")
        template = _read_prompt_template(task_name)
        prompt = _build_monthly_prompt(template, ten_day_text, prev_month_text, year, month)

        _update_progress(5, total_steps, "Claude 正在生成月度汇总...（通常 2-3 分钟）")
        output = _call_claude_cli(prompt, output_json=False)

        _update_progress(6, total_steps, "保存报告到 Obsidian...")
        report_dir = vault / config["paths"]["monthly_reports"]
        report_dir.mkdir(parents=True, exist_ok=True)
        report_name = f"{year}_{month:02d}_月度汇总.md"
        report_path = report_dir / report_name
        # 追加第十节「下月星象参考」占位——内容由 M8 下月星象模块（月末连体 3/3）后续写入
        # 该板块写进本月月报末尾，供下月日报读上月月报时能拿到当月星象参考
        next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
        astrology_placeholder = (
            f"\n\n## 十、下月星象参考（{next_y}-{next_m:02d}）\n\n"
            f"（待 M8 下月星象模块写入——查询 {next_y}-{next_m:02d} 的行星逆行 / 新月满月 / "
            f"重大相位，供 {next_y}-{next_m:02d} 的每日报告读本月月报时消费）\n"
        )
        report_path.write_text(output.rstrip() + astrology_placeholder, encoding="utf-8")

        _update_progress(6, total_steps, f"月度汇总已保存: {report_path.name}", status="done")
        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "month": f"{year}-{month:02d}",
            "ten_day_reports_count": ten_day_count,
            "prev_month_included": bool(prev_month_text),
            "output_path": str(report_path),
            "pending_followup": {
                "module": "M8_下月星象",
                "target_file": report_path.name,
                "target_section": f"第十节「下月星象参考（{next_y}-{next_m:02d})」",
                "hint": f"M3 月度汇总只写了前 9 节，第十节是占位段——需要尽快跑 M8 下月星象（查 {next_y}-{next_m:02d} 星象）补上。否则 {next_y}-{next_m:02d} 的 M1 每日报告读本月月报时读不到星象参考。",
            },
            "summary": (
                f"已生成 {year}-{month:02d} 月度汇总，"
                f"读入 {ten_day_count} 份十日报告"
                + ("（含上月月汇总作连续性对比）" if prev_month_text else "（无上月月汇总）")
                + f"，写入 {report_path.name}。⚠️ 第十节「下月星象参考」占位待 M8 下月星象补写。"
            ),
        }
        persist_run(result)
        return result

    if task_name == "life_growth_report":
        if date_str is None:
            raise ValueError("life_growth_report 需要指定 --date（月最后一天 YYYY-MM-DD）")
        _update_progress(2, total_steps, "校验日期为月最后一天...")
        year, month = _verify_last_day_of_month(date_str)

        _update_progress(3, total_steps, f"读取上版人生轨迹总览 + {year}-{month:02d} 月汇总...")
        prev_growth_text, prev_version_date = _read_prev_growth_report(vault, config)
        growth_path = _growth_report_path(vault, config)
        if not prev_growth_text:
            # 允许首次跑（空基线），但给出醒目提示
            print(f"[M4] 警告：{growth_path} 不存在或为空，将作为首次起草处理")
        month_summary_text = _read_current_month_summary(vault, year, month, config)
        if month_summary_text is None:
            _update_progress(0, 0, "本月月度汇总不存在", status="error")
            raise ValueError(
                f"{year}-{month:02d} 月度汇总不存在——M4 人生成长报告依赖月汇总作为塑造性筛选底料。"
                f"先跑 M3 月度汇总（同是月末连体，应在 M4 之前）。"
            )

        _update_progress(4, total_steps, "构建人生轨迹 prompt...")
        template = _read_prompt_template(task_name)
        prompt = _build_life_growth_prompt(
            template, prev_growth_text, month_summary_text, year, month, prev_version_date
        )

        _update_progress(5, total_steps, "Claude 正在更新人生轨迹总览...（通常 2-3 分钟）")
        output = _call_claude_cli(prompt, output_json=False)

        _update_progress(6, total_steps, "备份旧版 + 覆盖写入 Obsidian...")
        growth_path.parent.mkdir(parents=True, exist_ok=True)
        # 先备份旧版（只在旧版存在时备份）
        backup_path: Path | None = None
        if prev_growth_text:
            backup_dir = growth_path.parent / "人生轨迹总览.backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"人生轨迹总览.{year}_{month:02d}_backup.md"
            backup_path.write_text(prev_growth_text, encoding="utf-8")
        growth_path.write_text(output, encoding="utf-8")

        _update_progress(6, total_steps, f"人生轨迹总览已更新: {growth_path.name}", status="done")
        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "month": f"{year}-{month:02d}",
            "prev_version_date": prev_version_date,
            "is_first_run": not bool(prev_growth_text),
            "output_path": str(growth_path),
            "backup_path": str(backup_path) if backup_path else None,
            "summary": (
                f"已更新 {growth_path.name}，"
                + (f"上版日期 {prev_version_date}，" if prev_version_date else "首次起草，")
                + (f"旧版已备份到 {backup_path.name}" if backup_path else "无旧版可备份")
                + f"（月份基线 {year}-{month:02d}）。"
            ),
        }
        persist_run(result)
        return result

    if task_name == "next_month_astrology":
        if date_str is None:
            raise ValueError("next_month_astrology 需要指定 --date（月最后一天 YYYY-MM-DD）")
        _update_progress(2, total_steps, "校验日期为月最后一天...")
        year, month = _verify_last_day_of_month(date_str)

        _update_progress(3, total_steps, f"读取本月月报 + 上月月报的星象预测板块...")
        current_path = _monthly_report_path(vault, year, month, config)
        if not current_path.exists():
            _update_progress(0, 0, "本月月报不存在", status="error")
            raise FileNotFoundError(
                f"本月月报不存在：{current_path}——M8 依赖 M3 月度汇总的输出（第十节占位段），"
                f"先跑 M3 月度汇总再跑 M8 下月星象。"
            )
        current_full_text = current_path.read_text(encoding="utf-8")
        current_main, current_astrology_placeholder = _extract_astrology_section(current_full_text)
        if not current_astrology_placeholder:
            _update_progress(0, 0, "本月月报没有第十节占位段", status="error")
            raise ValueError(
                f"本月月报 {current_path.name} 找不到「## 十、下月星象参考」占位段——"
                f"可能 M3 月度汇总跑的是旧版 prompt（未生成占位段）。"
                f"先重跑 M3 月度汇总生成占位段，再跑 M8 下月星象。"
            )

        # 上月月报的第十节（= 当初对本月的预测）
        prev_y, prev_m = (year - 1, 12) if month == 1 else (year, month - 1)
        prev_path = _monthly_report_path(vault, prev_y, prev_m, config)
        prev_astrology_section = ""
        if prev_path.exists():
            prev_full = prev_path.read_text(encoding="utf-8")
            _, prev_astrology_section = _extract_astrology_section(prev_full)

        _update_progress(4, total_steps, "构建下月星象 prompt...")
        template = _read_prompt_template(task_name)
        prompt = _build_astrology_prompt(template, current_main, prev_astrology_section, year, month)

        _update_progress(5, total_steps, "Claude 正在查下月星象并做信用校准...（通常 1-2 分钟）")
        output = _call_claude_cli(prompt, output_json=False)

        _update_progress(6, total_steps, "替换本月月报第十节占位段...")
        # 校验 LLM 输出以 `## 十、下月星象参考` 开头——如果没有，加一个保险的包装
        stripped_output = output.strip()
        if not stripped_output.startswith(ASTROLOGY_SECTION_HEADER_PREFIX):
            # LLM 偏了，给个警告但还是尝试写入——把输出包在占位段标题下
            print(f"[M8] 警告：LLM 输出未以 `{ASTROLOGY_SECTION_HEADER_PREFIX}` 开头，自动补标题")
            next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
            stripped_output = f"## 十、下月星象参考（{next_y}-{next_m:02d}）\n\n{stripped_output}"

        new_full = current_main.rstrip() + "\n\n" + stripped_output + "\n"
        current_path.write_text(new_full, encoding="utf-8")

        _update_progress(6, total_steps, f"月报第十节已填入: {current_path.name}", status="done")
        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        next_y, next_m = (year + 1, 1) if month == 12 else (year, month + 1)
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "current_month": f"{year}-{month:02d}",
            "next_month_predicted": f"{next_y}-{next_m:02d}",
            "prev_prediction_included": bool(prev_astrology_section),
            "output_path": str(current_path),
            "summary": (
                f"已把 {next_y}-{next_m:02d} 的星象参考写入 {current_path.name} 第十节"
                + ("（含上月预测信用校准）" if prev_astrology_section else "（首次跑无上月预测可对照）")
                + f"。下月（{next_y}-{next_m:02d}）日报按规矩读本月月报时能自然拿到星象参考。"
            ),
        }
        persist_run(result)
        return result

    if task_name == "weekly_material_five":
        if date_str is None:
            raise ValueError("weekly_material_five 需要指定 --date（周日 YYYY-MM-DD）")
        _update_progress(2, total_steps, "校验日期为周日 + 计算本周窗口...")
        today_d = datetime.strptime(date_str, "%Y-%m-%d").date()
        monday, sunday = _get_week_bounds(today_d)

        _update_progress(3, total_steps, f"读取本周（{monday} ~ {sunday}）日报...")
        daily_reports_text, report_count = _read_weekly_daily_reports(vault, monday, sunday, config["paths"])
        if report_count < 3:
            _update_progress(0, 0, f"本周仅 {report_count} 篇日报，跳过 M5a", status="done")
            finished_at = now_local()
            result = {
                "run_id": finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}_skipped",
                "task": task_name,
                "label": task_config["label"],
                "status": "skipped",
                "profile": prof,
                "started_at": started_at.isoformat(timespec="seconds"),
                "finished_at": finished_at.isoformat(timespec="seconds"),
                "week_start": monday.isoformat(),
                "week_end": sunday.isoformat(),
                "daily_reports_count": report_count,
                "summary": (
                    f"本周（{monday} ~ {sunday}）仅 {report_count} 篇日报，不足 3 篇——M5a 素材库本周跳过，"
                    f"不调 Claude 节省额度。"
                ),
            }
            persist_run(result)
            return result

        material_dir = _material_library_dir(vault, config)
        material_dir.mkdir(parents=True, exist_ok=True)
        skeleton_text = _read_material_skeletons(material_dir)
        next_diff_idx = _next_diff_index(material_dir)

        _update_progress(4, total_steps, "构建 M5a 素材库 prompt...")
        template = _read_prompt_template(task_name)
        prompt = _build_weekly_material_prompt(
            template, daily_reports_text, skeleton_text, monday, sunday, next_diff_idx
        )

        _update_progress(5, total_steps, "Claude 正在提取本周五件套...（通常 2-3 分钟）")
        output = _call_claude_cli(prompt, output_json=False)

        _update_progress(6, total_steps, "解析分段并追加到各素材库文件...")
        segments = _parse_weekly_material_segments(output)

        files_touched: list[str] = []
        unknown_files: list[str] = []
        backup_dir: Path | None = None

        if segments:
            backup_dir = material_dir / ".backup" / f"weekly_{sunday.isoformat()}"
            backup_dir.mkdir(parents=True, exist_ok=True)

            for seg in segments:
                fname = seg["file"]
                if fname not in MATERIAL_LIBRARY_FILES:
                    unknown_files.append(fname)
                    print(f"[M5a] 警告：LLM 指向未注册文件 {fname}，跳过该分段")
                    continue
                target_path = material_dir / fname
                # 首次触达该文件 → 备份
                if fname not in files_touched and target_path.exists():
                    (backup_dir / fname).write_text(
                        target_path.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                _apply_segment_to_file(target_path, seg["anchor"], seg["mode"], seg["body"])
                if fname not in files_touched:
                    files_touched.append(fname)

        _update_progress(
            6, total_steps,
            f"本周五件套完成: {len(files_touched)}/5 文件被追加" if files_touched else "本周无可追加素材",
            status="done",
        )
        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "week_start": monday.isoformat(),
            "week_end": sunday.isoformat(),
            "daily_reports_count": report_count,
            "segments_count": len(segments),
            "files_touched": files_touched,
            "unknown_files_in_output": unknown_files,
            "backup_dir": str(backup_dir) if backup_dir else None,
            "summary": (
                (
                    f"已追加本周（{monday} ~ {sunday}）素材：{len(segments)} 个分段写入 "
                    f"{len(files_touched)}/5 文件（{', '.join(files_touched)}）。"
                )
                if files_touched
                else f"本周（{monday} ~ {sunday}）读入 {report_count} 篇日报，Claude 判断无可写素材——各文件一字未改。"
            ),
        }
        persist_run(result)
        return result

    if task_name == "monthly_knowledge_graph":
        if date_str is None:
            raise ValueError("monthly_knowledge_graph 需要指定 --date（月最后一天 YYYY-MM-DD）")
        _update_progress(2, total_steps, "校验日期为月最后一天...")
        year, month = _verify_last_day_of_month(date_str)

        _update_progress(3, total_steps, f"读取当前知识图谱 + 本月 5 件套增量 + 本月月汇总...")
        kg_path = _knowledge_graph_path(vault, config)
        current_kg_text = kg_path.read_text(encoding="utf-8") if kg_path.exists() else ""
        monthly_additions = _read_monthly_material_additions(vault, year, month, config)
        month_summary_text = _read_current_month_summary(vault, year, month, config)
        if month_summary_text is None:
            _update_progress(0, 0, "本月月度汇总不存在", status="error")
            raise ValueError(
                f"{year}-{month:02d} 月度汇总不存在——M5b 知识图谱依赖月汇总作为主题底料。"
                f"先跑 M3 月度汇总（同是月末连体，应在 M5b 之前）。"
            )

        _update_progress(4, total_steps, "构建 M5b 知识图谱 prompt...")
        template = _read_prompt_template(task_name)
        prompt = _build_knowledge_graph_prompt(
            template, current_kg_text, monthly_additions, month_summary_text, year, month
        )

        _update_progress(5, total_steps, "Claude 正在更新知识图谱...（通常 3-5 分钟）")
        output = _call_claude_cli(prompt, output_json=False)

        _update_progress(6, total_steps, "备份旧版 + 覆盖写入 Obsidian...")
        kg_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path: Path | None = None
        if current_kg_text:
            backup_dir = kg_path.parent / ".backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup_path = backup_dir / f"知识图谱_物理×认知×心理.{year}_{month:02d}_backup.md"
            backup_path.write_text(current_kg_text, encoding="utf-8")
        kg_path.write_text(output, encoding="utf-8")

        _update_progress(6, total_steps, f"知识图谱已更新: {kg_path.name}", status="done")
        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "month": f"{year}-{month:02d}",
            "is_first_run": not bool(current_kg_text),
            "output_path": str(kg_path),
            "backup_path": str(backup_path) if backup_path else None,
            "summary": (
                f"已更新 {kg_path.name}，"
                + (f"旧版已备份到 {backup_path.name}" if backup_path else "首次起草无旧版可备份")
                + f"（月份基线 {year}-{month:02d}）。"
            ),
        }
        persist_run(result)
        return result

    if task_name == "daily_analysis_state":
        _update_progress(3, total_steps, "加载已有状态用于去重...")
        existing_state = _load_existing_state(vault, config)
        prompt = _build_claude_prompt(task_name, journal_text, existing_state, date_str=date_str)

        _update_progress(4, total_steps, "Claude 正在提取结构化状态...")
        raw_output = _call_claude_cli(prompt, output_json=True)

        # Parse JSON from Claude output
        # Claude --output-format json wraps output in a JSON envelope with a "result" field
        # The "result" field may contain markdown code block markers (```json ... ```)
        import re

        def _extract_json(text: str) -> dict[str, Any]:
            """Strip markdown code fences and parse JSON."""
            cleaned = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
            cleaned = re.sub(r'\n?```\s*$', '', cleaned)
            return json.loads(cleaned)

        try:
            envelope = json.loads(raw_output)
            if isinstance(envelope, dict) and "result" in envelope:
                state_output = _extract_json(envelope["result"])
            else:
                state_output = envelope
        except json.JSONDecodeError:
            json_match = re.search(r'\{[\s\S]*\}', raw_output)
            if json_match:
                state_output = json.loads(json_match.group())
            else:
                raise RuntimeError(f"Claude output is not valid JSON: {raw_output[:300]}")

        # 1.5: Update concept_index
        concept_updates = state_output.get("concepts", {}).get("index_updates", [])
        concept_cands = state_output.get("concepts", {}).get("candidates", [])
        if concept_updates:
            _update_concept_index(vault, config, concept_updates)

        # 1.6: Update concept_candidates
        if concept_cands:
            _update_concept_candidates(vault, config, concept_cands)

        _update_progress(5, total_steps, "保存状态数据...")
        # Save the full state output
        state_dir = vault / config["paths"]["system_state"]
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / f"daily_state_{date_str}.json"
        write_json(state_path, state_output)

        finished_at = now_local()
        run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
        result = {
            "run_id": run_id,
            "task": task_name,
            "label": task_config["label"],
            "status": "completed",
            "profile": prof,
            "started_at": started_at.isoformat(timespec="seconds"),
            "finished_at": finished_at.isoformat(timespec="seconds"),
            "journal_date": date_str,
            "journal_hash": journal_hash,
            "output_path": str(state_path),
            "concepts_updated": len(concept_updates),
            "concepts_candidates_added": len(concept_cands),
            "beliefs_new": len(state_output.get("beliefs", {}).get("new", [])),
            "patterns_new": len(state_output.get("patterns", {}).get("new", [])),
            "reminders_candidates": len(state_output.get("reminders", {}).get("candidates", [])),
            "summary": (
                f"已提取 {date_str} 的结构化状态: "
                f"{len(concept_updates)} 概念更新, {len(concept_cands)} 新概念候选, "
                f"{len(state_output.get('beliefs', {}).get('new', []))} 新信念, "
                f"{len(state_output.get('patterns', {}).get('new', []))} 新模式"
            ),
        }
        _update_progress(5, total_steps, "全部完成", status="done")
        persist_run(result)
        return result

    raise ValueError(f"Unsupported Claude task: {task_name}")


def make_demo_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    pages = payload["pages"]
    home = pages["home"]
    return {
        "page_types": list(pages.keys()),
        "home": {
            "pattern_count": len(home.get("patterns", [])),
            "belief_count": len(home.get("belief_migrations", [])),
            "capability_count": len(home.get("capabilities", [])),
            "mechanism_count": len(home.get("verified_mechanisms", [])),
        },
        "daily_report": {
            "title": pages["daily_report"].get("title"),
            "action_count": len(pages["daily_report"].get("daily_actions", [])),
        },
        "tenday_report": {
            "title": pages["tenday_report"].get("title"),
            "phase_count": len(pages["tenday_report"].get("phase_segments", [])),
        },
        "monthly_report": {
            "title": pages["monthly_report"].get("title"),
            "open_topic_count": len(pages["monthly_report"].get("open_topics", [])),
        },
        "report_counts": count_report_types(payload["report_index"]),
        "reminder_counts": count_reminder_statuses(payload.get("reminders", {"items": []})),
        "suggestion_count": len(payload.get("suggestion_index", {}).get("items", [])),
        "warning_count": len(payload.get("warnings", [])),
    }


def available_tasks_payload() -> list[dict[str, Any]]:
    return list(task_registry().values())


def persist_run(result: dict[str, Any]) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_path = RUNS_DIR / f"{result['run_id']}.json"
    write_json(run_path, result)

    existing = read_existing_runtime()
    recent_runs = existing.get("recent_runs", [])
    recent_runs = [result] + recent_runs[:9]
    runtime_payload = {
        "updated_at": result["finished_at"],
        "profile": result["profile"],
        "available_tasks": available_tasks_payload(),
        "last_run": result,
        "recent_runs": recent_runs,
        "workbench_path": str(WORKBENCH_JSON),
    }
    write_json(RUNTIME_OUTPUT, runtime_payload)


def run_task(task_name: str, profile: str | None = None, write_workspace_output: bool = True, date_str: str | None = None) -> dict[str, Any]:
    registry = task_registry()
    if task_name not in registry:
        available = ", ".join(sorted(registry.keys()))
        raise ValueError(f'Unknown task "{task_name}". Available tasks: {available}')

    # Route Claude CLI tasks to the new execution path
    if task_name in CLAUDE_TASKS:
        result = run_claude_task(task_name, profile=profile, date_str=date_str)
        _refresh_mirror_scale()  # 任务跑完自动重生成 mirror-scale.json
        return result

    generator = load_generator_module()
    started_at = now_local()
    payload = generator.build_payload(profile)
    if write_workspace_output:
        generator.write_workspace_outputs(payload)

    snapshot, summary, inputs = make_snapshot(task_name, payload)
    task = registry[task_name]
    finished_at = now_local()
    run_id = finished_at.strftime("%Y%m%dT%H%M%S") + f"_{task_name}"
    result = {
        "run_id": run_id,
        "task": task_name,
        "label": task["label"],
        "description": task["description"],
        "status": "completed",
        "profile": payload["profile"],
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "prompt_path": task["prompt_path"],
        "prompt_summary": task["prompt_summary"],
        "artifacts": payload["artifact_paths"],
        "inputs": inputs,
        "warnings": payload.get("warnings", []),
        "snapshot": snapshot,
        "summary": summary,
    }
    persist_run(result)
    return result


def run_demo(profile: str | None = None, write_workspace_output: bool = True) -> dict[str, Any]:
    generator = load_generator_module()
    started_at = now_local()
    payload = generator.build_payload(profile)
    if write_workspace_output:
        generator.write_workspace_outputs(payload)

    registry = task_registry()
    task_results: list[dict[str, Any]] = []
    for task_name in registry:
        snapshot, summary, inputs = make_snapshot(task_name, payload)
        task = registry[task_name]
        task_results.append(
            {
                "task": task_name,
                "label": task["label"],
                "summary": summary,
                "inputs": inputs,
                "snapshot": snapshot,
            }
        )

    finished_at = now_local()
    run_id = finished_at.strftime("%Y%m%dT%H%M%S") + "_mvp_demo"
    result = {
        "run_id": run_id,
        "task": "mvp_demo",
        "label": "认知镜 MVP Demo",
        "description": "按 sample_vault 刷新页面 payload、状态文件和 demo 静态数据。",
        "status": "completed",
        "profile": payload["profile"],
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "prompt_path": None,
        "prompt_summary": "主 Agent 运行层：一次刷新所有页面 payload 与状态文件。",
        "artifacts": payload["artifact_paths"],
        "inputs": [
            payload["state"]["meta"].get("latest_daily_report"),
            payload["state"]["meta"].get("latest_ten_day_report"),
            payload["state"]["meta"].get("latest_monthly_report"),
            payload["state"]["meta"].get("latest_growth_report"),
        ],
        "warnings": payload.get("warnings", []),
        "snapshot": make_demo_snapshot(payload),
        "summary": "已刷新 MVP demo 所需的全部页面 payload、状态文件和静态预览数据。",
        "task_results": task_results,
    }
    result["inputs"] = [item for item in result["inputs"] if item]
    persist_run(result)
    return result


def get_agent_status() -> dict[str, Any]:
    runtime = read_existing_runtime()
    runtime["available_tasks"] = available_tasks_payload()
    runtime["workbench_exists"] = WORKBENCH_JSON.exists()
    return runtime


def get_workbench_payload(profile: str | None = None, refresh_if_missing: bool = False) -> dict[str, Any]:
    if WORKBENCH_JSON.exists():
        return load_json(WORKBENCH_JSON, {})
    if not refresh_if_missing:
        raise FileNotFoundError(f"Workbench payload not found: {WORKBENCH_JSON}")
    generator = load_generator_module()
    payload = generator.build_payload(profile)
    generator.write_workspace_outputs(payload)
    return payload


def list_reminders(profile: str | None = None, refresh_if_missing: bool = False) -> dict[str, Any]:
    payload = get_workbench_payload(profile=profile, refresh_if_missing=refresh_if_missing)
    return payload.get("reminders", {"generated_at": None, "items": []})


def update_reminder_status(
    reminder_id: str,
    status: str,
    profile: str | None = None,
    snooze_until: str | None = None,
) -> dict[str, Any]:
    if status not in {"new", "active", "done", "snoozed", "dismissed"}:
        raise ValueError(f"Unsupported reminder status: {status}")

    paths = resolve_paths(profile)
    reminders_path = paths["reminders"]
    reminders = load_json(reminders_path, {"generated_at": None, "items": []})
    items = reminders.get("items", [])
    target = next((item for item in items if item.get("id") == reminder_id), None)
    if not target:
        raise ValueError(f"Reminder not found: {reminder_id}")

    now = now_local().isoformat(timespec="seconds")
    target["status"] = status
    target["updated_at"] = now
    if status == "done":
        target["done_at"] = now
        target["snooze_until"] = None
    elif status == "snoozed":
        if not snooze_until:
            snooze_until = (now_local() + timedelta(days=7)).isoformat(timespec="seconds")
        target["snooze_until"] = snooze_until
        target["done_at"] = None
    else:
        target["done_at"] = None if status in {"new", "active"} else target.get("done_at")
        target["snooze_until"] = None

    reminders["generated_at"] = now
    write_json(reminders_path, reminders)

    generator = load_generator_module()
    payload = generator.build_payload(profile)
    generator.write_workspace_outputs(payload)

    updated = next((item for item in payload.get("reminders", {}).get("items", []) if item.get("id") == reminder_id), None)
    result = {
        "updated_at": now,
        "profile": payload["profile"],
        "reminder": updated,
        "warnings": payload.get("warnings", []),
    }
    return result
