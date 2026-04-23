#!/usr/bin/env python3
"""Dimension usage tracking — build/update dimension_usage_index.json from daily reports."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = WORKSPACE_ROOT / "config" / "agent.config.json"
DIMENSIONS_PATH = WORKSPACE_ROOT / "config" / "dimensions.json"


def load_dimensions() -> dict[str, Any]:
    """Load single-source dimension config. Returns the 'dimensions' subtree."""
    raw = json.loads(DIMENSIONS_PATH.read_text(encoding="utf-8"))
    return raw["dimensions"]


def _build_categories(dims: dict[str, Any]) -> dict[str, list[str]]:
    return {dim: list(d["categories"].keys()) for dim, d in dims.items()}


def _build_keywords(dims: dict[str, Any]) -> dict[str, dict[str, list[str]]]:
    return {
        dim: {cat: meta.get("keywords", []) for cat, meta in d["categories"].items()}
        for dim, d in dims.items()
    }


# 从 config/dimensions.json 派生（模块加载时读取一次）
DIMENSIONS = load_dimensions()
CATEGORIES = _build_categories(DIMENSIONS)
KEYWORDS: dict[str, dict[str, list[str]]] = _build_keywords(DIMENSIONS)

# 维度小节标题（从标题到下一个 #### 之间是该维度的正文）
SECTION_HEADERS = {
    "psy": "🧠 心理学分析",
    "meta": "🌌 玄学分析",
    "phy": "⚛️ 物理学视角",
}

TAG_PATTERN = re.compile(
    r"<!--\s*dimensions:\s*psy=([^;]+);\s*meta=([^;]+);\s*phy=([^>]+?)\s*-->",
    re.IGNORECASE,
)

FILENAME_PATTERN = re.compile(r"(\d{4})_(\d{2})_(\d{2})_日志整理与分析\.md$")


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat(timespec="seconds")


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def vault_root(profile: str | None = None) -> Path:
    config = load_config()
    prof = profile or config.get("default_profile", "prod")
    return Path(config["profiles"][prof]["vault_root"]).expanduser()


def index_path(profile: str | None = None) -> Path:
    config = load_config()
    indexes_rel = config["paths"]["indexes"]
    return vault_root(profile) / indexes_rel / "dimension_usage_index.json"


def iter_report_files(vault: Path) -> list[Path]:
    reports_root = vault / "可实现" / "关于自己" / "每日报告"
    if not reports_root.exists():
        return []
    files: list[Path] = []
    for p in reports_root.rglob("*_日志整理与分析.md"):
        if FILENAME_PATTERN.search(p.name):
            files.append(p)
    return sorted(files)


def extract_date(path: Path) -> str | None:
    m = FILENAME_PATTERN.search(path.name)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def parse_tag(text: str) -> dict[str, str] | None:
    m = TAG_PATTERN.search(text)
    if not m:
        return None
    return {"psy": m.group(1).strip(), "meta": m.group(2).strip(), "phy": m.group(3).strip()}


def extract_section(text: str, header: str) -> str:
    """Return the text between a `###`/`####` {header} and the next heading of level ##-####."""
    # header 可能带延伸后缀（如 "⚛️ 物理学视角——信噪比"），用 [^\n]* 吸掉同行剩余部分
    pattern = re.compile(rf"#{{3,4}}\s*{re.escape(header)}[^\n]*\n(.*?)(?=\n#{{2,4}}\s|\Z)", re.DOTALL)
    m = pattern.search(text)
    return m.group(1) if m else ""


def guess_category(section_text: str, dim: str) -> str | None:
    if not section_text:
        return None
    scores: dict[str, int] = {}
    for cat, keywords in KEYWORDS[dim].items():
        score = 0
        for kw in keywords:
            score += section_text.count(kw)
        # 加粗小标题里直接命中大类名，加重权重
        bold_pattern = re.compile(rf"\*\*[^*]*{re.escape(cat)}[^*]*\*\*")
        score += 5 * len(bold_pattern.findall(section_text))
        if score > 0:
            scores[cat] = score
    if not scores:
        return None
    best = max(scores.items(), key=lambda kv: kv[1])
    return best[0] if best[1] >= 1 else None


def analyze_report(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    date = extract_date(path)
    if not date:
        return {"date": None, "error": "bad filename"}

    tag = parse_tag(text)
    if tag:
        return {"date": date, "psy": tag["psy"], "meta": tag["meta"], "phy": tag["phy"], "source": "tag"}

    # Fallback: keyword-based guess
    entry: dict[str, Any] = {"date": date, "source": "keyword"}
    for dim, header in SECTION_HEADERS.items():
        section = extract_section(text, header)
        cat = guess_category(section, dim)
        entry[dim] = cat or "unknown"
    return entry


def validate_entry(entry: dict[str, Any]) -> list[str]:
    """Return warnings if category names don't match the canonical list."""
    warnings = []
    for dim in ("psy", "meta", "phy"):
        val = entry.get(dim)
        if val and val != "unknown" and val not in CATEGORIES[dim]:
            warnings.append(f"{entry['date']} {dim}={val} 不在大类清单里")
    return warnings


def build_index(profile: str | None = None, days: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    vault = vault_root(profile)
    files = iter_report_files(vault)
    if days:
        files = files[-days:]

    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for f in files:
        entry = analyze_report(f)
        if entry.get("date"):
            entries.append(entry)
            warnings.extend(validate_entry(entry))

    payload = {
        "updated_at": now_iso(),
        "categories": CATEGORIES,
        "entries": entries,
    }

    if not dry_run:
        path = index_path(profile)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {"payload": payload, "warnings": warnings, "path": str(index_path(profile))}


def update_from_report(report_path: Path, profile: str | None = None) -> dict[str, Any] | None:
    """Parse one report and upsert its entry into the index. Called by runtime after a report is written."""
    if not report_path.exists():
        return None
    entry = analyze_report(report_path)
    if not entry.get("date"):
        return None

    path = index_path(profile)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {"categories": CATEGORIES, "entries": []}

    entries = data.get("entries", [])
    entries = [e for e in entries if e.get("date") != entry["date"]]
    entries.append(entry)
    entries.sort(key=lambda e: e.get("date") or "")

    data["categories"] = CATEGORIES
    data["entries"] = entries
    data["updated_at"] = now_iso()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry


def format_category_list_for_prompt(dim: str) -> str:
    """Render one dimension's categories as the bullet list used in the prompt.

    Output matches the pre-refactor hardcoded block — one bullet per category,
    name in bold, description after a Chinese dash. Source of truth is
    config/dimensions.json so this stays in sync with the keyword fallback.
    """
    if dim not in DIMENSIONS:
        raise ValueError(f"unknown dimension: {dim}")
    lines = []
    for cat, meta in DIMENSIONS[dim]["categories"].items():
        desc = meta.get("description", "")
        lines.append(f"- **{cat}**——{desc}")
    return "\n".join(lines)


def format_recent_for_prompt(profile: str | None = None, days: int = 7, before_date: str | None = None) -> str:
    """Format the 'recently used' block that gets injected into {{RECENT_DIMENSIONS}}."""
    used = recent_usage(profile=profile, days=days, before_date=before_date)
    psy = "、".join(used["psy"]) or "（暂无记录）"
    meta = "、".join(used["meta"]) or "（暂无记录）"
    phy = "、".join(used["phy"]) or "（暂无记录）"
    return (
        f"**最近 {days} 天已经用过的大类**（请尽量换一个没用过的角度切入）：\n"
        f"- 心理（psy）：{psy}\n"
        f"- 玄学（meta）：{meta}\n"
        f"- 物理（phy）：{phy}"
    )


def recent_usage(profile: str | None = None, days: int = 7, before_date: str | None = None) -> dict[str, list[str]]:
    """Return {dim: [categories used in last N days]}, excluding before_date."""
    path = index_path(profile)
    if not path.exists():
        return {"psy": [], "meta": [], "phy": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    entries = [e for e in entries if e.get("date")]
    entries.sort(key=lambda e: e["date"], reverse=True)

    # Exclude the target day itself if provided
    if before_date:
        entries = [e for e in entries if e["date"] < before_date]

    recent = entries[:days]
    used: dict[str, list[str]] = {"psy": [], "meta": [], "phy": []}
    for e in recent:
        for dim in ("psy", "meta", "phy"):
            v = e.get(dim)
            if v and v != "unknown" and v not in used[dim]:
                used[dim].append(v)
    return used


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/update dimension_usage_index.json")
    parser.add_argument("--profile", default=None, help="config profile (default: prod)")
    parser.add_argument("--days", type=int, default=None, help="only process the most recent N reports")
    parser.add_argument("--dry-run", action="store_true", help="print result without writing")
    parser.add_argument("--show", action="store_true", help="print entries table after building")
    args = parser.parse_args(argv)

    result = build_index(profile=args.profile, days=args.days, dry_run=args.dry_run)

    print(f"index: {result['path']}")
    print(f"entries: {len(result['payload']['entries'])}")
    if result["warnings"]:
        print("warnings:")
        for w in result["warnings"]:
            print(f"  - {w}")

    if args.show:
        print()
        print(f"{'date':<12} {'psy':<16} {'meta':<14} {'phy':<12} source")
        for e in result["payload"]["entries"]:
            print(f"{e['date']:<12} {e.get('psy','-'):<16} {e.get('meta','-'):<14} {e.get('phy','-'):<12} {e.get('source','?')}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
