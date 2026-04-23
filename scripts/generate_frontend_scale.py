#!/usr/bin/env python3
"""
generate_frontend_scale.py · 规模感数据生成器

为认知镜前端 Hero 生成「累积规模」快照：
- 报告总数（日报 / 十日报 / 月汇 / 人生报）
- 素材库五件套分布
- 知识图谱概念三类分布

输出：
- data/generated/mirror-scale.json
- apps/cognitive-mirror-preview/public/mirror-scale.json（前端消费）

隐私原则：只输出计数、分类名、日期；绝不输出原文/标题/具体事件。
"""

from __future__ import annotations
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "agent.config.json"
OUT_PATHS = [
    ROOT / "data" / "generated" / "mirror-scale.json",
    ROOT / "apps" / "cognitive-mirror-preview" / "public" / "mirror-scale.json",
]

MATERIAL_FILES = {
    "主题线索": "素材库_主题线索.md",
    "原创洞察": "素材库_原创洞察.md",
    "思维差异": "素材库_思维差异.md",
    "场景片段": "素材库_场景片段.md",
    "金句集": "素材库_金句集.md",
}


def load_config() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_vault_root(cfg: dict) -> Path:
    profile_name = cfg.get("default_profile", "prod")
    profile = cfg.get("profiles", {}).get(profile_name, {})
    vault = profile.get("vault_root")
    if not vault:
        raise RuntimeError(f"config 里 profile={profile_name} 缺 vault_root")
    return Path(vault).expanduser()


def count_md(dir_path: Path) -> int:
    if not dir_path.exists():
        return 0
    return sum(1 for _ in dir_path.rglob("*.md"))


def count_third_headings(md_file: Path) -> int:
    if not md_file.exists():
        return 0
    count = 0
    with md_file.open(encoding="utf-8") as f:
        for line in f:
            if line.startswith("### "):
                count += 1
    return count


def count_quotes_in_pool(md_file: Path) -> int:
    """金句集是 markdown 表格：数 `|` 开头的 data row（排除表头和分隔符）"""
    if not md_file.exists():
        return 0
    count = 0
    prev_was_header = False
    with md_file.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s.startswith("|"):
                prev_was_header = False
                continue
            # 分隔符行 |---|---|
            if re.match(r"^\|[\s\-:|]+\|?\s*$", s):
                prev_was_header = False
                continue
            # 表头：紧跟分隔符的上一行通常是表头
            # 策略：任何 | 行如果下一行是分隔符，则它是表头
            # 这里用简化策略：往回看 prev_was_header
            if prev_was_header:
                prev_was_header = False
                continue
            count += 1
            prev_was_header = True  # 可能是表头，等下一行是分隔符才确认
    # 上面逻辑过于简化，改用更稳妥的两遍扫描
    count = 0
    with md_file.open(encoding="utf-8") as f:
        lines = [ln.rstrip() for ln in f]
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        # 发现表头（| 开头 + 下一行是分隔符）
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s\-:|]+\|?\s*$", lines[i + 1].strip()):
            # 跳过表头和分隔符
            i += 2
            # 数后续连续 | 开头行
            while i < len(lines) and lines[i].strip().startswith("|") and not re.match(r"^\|[\s\-:|]+\|?\s*$", lines[i].strip()):
                count += 1
                i += 1
            continue
        i += 1
    return count


def count_quote_pool_from_workbench(root: Path) -> int | None:
    """优先从已生成的 cognitive-workbench-data.json 的 library_stats 读 quote_count"""
    p = root / "data" / "generated" / "cognitive-workbench-data.json"
    if not p.exists():
        return None
    try:
        with p.open(encoding="utf-8") as f:
            d = json.load(f)
        return d.get("pages", {}).get("home", {}).get("library_stats", {}).get("quote_count")
    except Exception:
        return None


def scan_material_library(vault: Path, rel: str) -> dict:
    base = vault / rel
    categories = []
    total = 0
    pool_from_workbench = count_quote_pool_from_workbench(ROOT)
    for name, fname in MATERIAL_FILES.items():
        fpath = base / fname
        if name == "金句集":
            n = count_quotes_in_pool(fpath)
            # 如果扫描到的数 < workbench 里的 quote_count，以 workbench 为准
            if pool_from_workbench is not None and pool_from_workbench > n:
                n = pool_from_workbench
        else:
            n = count_third_headings(fpath)
        categories.append({"name": name, "count": n})
        total += n
    return {"total": total, "categories": categories}


def scan_knowledge_graph(vault: Path, rel: str) -> dict:
    """知识图谱：扫三大类分区内的 ### 概念条目"""
    fpath = vault / rel
    result = {
        "concept_total": 0,
        "categories": [],
        "cross_domain_links": 0,
        "top_concepts": [],
    }
    if not fpath.exists():
        return result

    section_patterns = [
        ("物理学", re.compile(r"^##\s+一[、\.]")),
        ("认知行为学", re.compile(r"^##\s+二[、\.]")),
        ("心理学", re.compile(r"^##\s+三[、\.]")),
    ]
    cross_pattern = re.compile(r"^##\s+四[、\.]")
    index_pattern = re.compile(r"^##\s+五[、\.]")

    current_cat = None
    counts = {name: 0 for name, _ in section_patterns}
    concept_names = {name: [] for name, _ in section_patterns}
    cross_links = 0
    concept_ref_count = {}  # name -> 粗略"被引用次数" 基于 [[ 双链或 `被引用` 标注

    with fpath.open(encoding="utf-8") as f:
        content = f.read()

    # 第一遍：粗分段 + 计数
    for line in content.splitlines():
        matched_section = False
        for name, pat in section_patterns:
            if pat.match(line):
                current_cat = name
                matched_section = True
                break
        if matched_section:
            continue
        if cross_pattern.match(line) or index_pattern.match(line):
            current_cat = "_other"
            continue
        if line.startswith("### ") and current_cat in counts:
            counts[current_cat] += 1
            raw = line[4:].strip()
            # 去掉编号 "1. " 或 "12. " 和 "（英文）"
            name_cn = re.sub(r"^\d+\.\s*", "", raw)
            name_cn = re.sub(r"[（(][^）)]*[）)]\s*$", "", name_cn).strip()
            if name_cn:
                concept_names[current_cat].append(name_cn)

    # 第二遍：被引用次数（粗略：看每个概念名在全文中出现次数，减 1 去掉自身标题）
    all_names = [n for lst in concept_names.values() for n in lst]
    for n in all_names:
        if len(n) < 2:
            continue
        occurrences = content.count(n)
        # 超过 1 次才有意义（至少在自身标题 + 其他地方提到）
        ref = max(0, occurrences - 1)
        if ref > 0:
            concept_ref_count[n] = ref

    # Top 5 最常出现的
    top = sorted(concept_ref_count.items(), key=lambda x: -x[1])[:5]
    result["top_concepts"] = [{"name": n, "refs": c} for n, c in top]

    # 跨领域连接：数第四节里的连接条目（简单：### 或列表条目）
    four_section = re.search(r"##\s+四[、\.][^\n]*\n(.*?)(?=\n##\s+|\Z)", content, re.DOTALL)
    if four_section:
        body = four_section.group(1)
        cross_links = sum(1 for line in body.splitlines() if line.strip().startswith(("- ", "* ", "1.", "2.", "3.", "### ")))

    result["concept_total"] = sum(counts.values())
    result["categories"] = [
        {"name": name, "count": counts[name]} for name, _ in section_patterns
    ]
    result["cross_domain_links"] = cross_links
    return result


def scan_reports(vault: Path, paths_cfg: dict) -> dict:
    daily_dir = vault / paths_cfg.get("daily_reports", "")
    ten_dir = vault / paths_cfg.get("ten_day_reports", "")
    monthly_dir = vault / paths_cfg.get("monthly_reports", "")
    growth = vault / paths_cfg.get("growth_report", "")

    return {
        "daily_total": count_md(daily_dir),
        "ten_day_total": count_md(ten_dir),
        "monthly_total": count_md(monthly_dir),
        "growth_exists": growth.is_file(),
    }


def now_iso() -> str:
    tz = timezone(timedelta(hours=8))
    return datetime.now(tz).isoformat(timespec="seconds")


def main() -> int:
    cfg = load_config()
    vault = resolve_vault_root(cfg)
    paths_cfg = cfg.get("paths", {})

    out = {
        "generated_at": now_iso(),
        "vault_root": str(vault),
        "reports": scan_reports(vault, paths_cfg),
        "material_library": scan_material_library(vault, paths_cfg.get("material_library", "")),
        "knowledge_graph": scan_knowledge_graph(vault, paths_cfg.get("knowledge_graph", "")),
    }

    for p in OUT_PATHS:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"✓ 写入 {p.relative_to(ROOT)}")

    # 摘要打印（无隐私）
    print()
    print("=== 规模快照 ===")
    r = out["reports"]
    print(f"  报告:  日报 {r['daily_total']} · 十日 {r['ten_day_total']} · 月汇 {r['monthly_total']} · 人生报 {'✓' if r['growth_exists'] else '—'}")
    m = out["material_library"]
    print(f"  素材库: 合计 {m['total']} 条")
    for c in m["categories"]:
        print(f"    · {c['name']}: {c['count']}")
    kg = out["knowledge_graph"]
    print(f"  知识图谱: {kg['concept_total']} 概念 · 跨领域连接 {kg['cross_domain_links']}")
    for c in kg["categories"]:
        print(f"    · {c['name']}: {c['count']}")
    if kg["top_concepts"]:
        print("  最常出现概念 Top 5:")
        for c in kg["top_concepts"]:
            print(f"    · {c['name']} × {c['refs']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
