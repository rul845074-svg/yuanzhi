#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = WORKSPACE_ROOT / "config" / "agent.config.json"
JSON_OUTPUT = WORKSPACE_ROOT / "data" / "generated" / "cognitive-workbench-data.json"
JS_OUTPUT = WORKSPACE_ROOT / "data" / "generated" / "cognitive-workbench-data.js"
PREVIEW_PUBLIC_OUTPUT = WORKSPACE_ROOT / "apps" / "cognitive-mirror-preview" / "public" / "cognitive-workbench-data.js"
PREVIEW_DIST_OUTPUT = WORKSPACE_ROOT / "apps" / "cognitive-mirror-preview" / "dist" / "cognitive-workbench-data.js"

STATUS_LABELS = {
    "candidate": "候选",
    "active": "活跃",
    "aware": "已觉察",
    "loosening": "松动",
    "rewriting": "重写中",
    "dormant": "休眠",
}

PATTERN_LIBRARY = {
    '反复向AI确认=向人求认可': {
        "id": "p01",
        "professional_name": "外部确认依赖",
        "pattern_type": "外部验证依赖",
        "source_system": "依恋理论 (Bowlby)",
        "summary": "判断成立感被外包给外部回应，导致行动前需要重复确认与关系性许可。",
        "rewrite_target": "自己先判断，再让外部验证",
    },
    '我不该花这个钱的内疚循环': {
        "id": "p02",
        "professional_name": "自我剥夺性内疚",
        "pattern_type": "匮乏型自我惩罚",
        "source_system": "图式疗法",
        "summary": "一旦资源流向自己，系统会自动启动内疚和自我审判来回收享受权。",
        "rewrite_target": "把资源投入自己视为正常配置",
    },
    '等别人来发现我的被动等待': {
        "id": "p03",
        "professional_name": "被动确认等待",
        "pattern_type": "行动启动延迟",
        "source_system": "习得性无助",
        "summary": "重要行动被拖到外部邀请或确认出现之后，主体启动权被让渡给外部环境。",
        "rewrite_target": "自己先发起，再让反馈跟上",
    },
    '气势不足导致的整体失利': {
        "id": "p04",
        "professional_name": "表达抑制与气势塌陷",
        "pattern_type": "公开表达抑制",
        "source_system": "社会评价威胁",
        "summary": "内容判断并不落后，但在高压场景里会因气势不足导致输出功率明显下滑。",
        "rewrite_target": "先稳住气势，再组织表达内容",
    },
    '边界侵犯→被迫听的模式': {
        "id": "p05",
        "professional_name": "边界侵入敏感",
        "pattern_type": "关系边界失守",
        "source_system": "界限理论",
        "summary": "对他人越界输入高度敏感，却长期以压抑和被动承受来维持表面关系稳定。",
        "rewrite_target": "及时表达需求，缩短受委屈到反应的时差",
    },
    '凌晨高效的神秘性': {
        "id": "p06",
        "professional_name": "夜间高专注窗口",
        "pattern_type": "节律性高效",
        "source_system": "注意力节律",
        "summary": "高质量输出更容易在低噪声、低打扰、倒计时明确的窗口自然出现。",
        "rewrite_target": "围绕低噪声时段主动设计深度工作",
    },
    '对物理/高阶理论的吸引与恐惧': {
        "id": "p07",
        "professional_name": "高阶认知趋近-回避",
        "pattern_type": "知识权威焦虑",
        "source_system": "趋近-回避冲突",
        "summary": "系统一边被高阶理论强烈吸引，一边又因身份与门槛想象而主动拉开距离。",
        "rewrite_target": "把高阶理论从神殿拉回到可进入的练习场",
    },
}

BELIEF_DOMAIN_LIBRARY = {
    '我不配拥有好东西': {"id": "b01", "domain": "自我价值", "source_system": "图式重写"},
    '反复确认才敢行动': {"id": "b02", "domain": "自我信任", "source_system": "认知重建"},
    '我的付出不被看见': {"id": "b03", "domain": "关系可见性", "source_system": "关系修复"},
    '如果我太强别人会排斥我': {"id": "b04", "domain": "力量表达", "source_system": "羞耻修复"},
    '没有专业背景就没发言权': {"id": "b05", "domain": "能力认同", "source_system": "自我效能感"},
    '帮了别人等于牺牲自己': {"id": "b06", "domain": "给予边界", "source_system": "关系边界"},
    '在家里我不如姐姐重要': {"id": "b07", "domain": "家庭归属", "source_system": "家庭叙事重写"},
    '需求=负担，开口=代价': {"id": "b08", "domain": "需求表达", "source_system": "界限训练"},
}

CAPABILITY_SOURCE_LIBRARY = {
    '自我觉察': "元认知",
    '边界表达': "界限理论",
    'AI协作': "增强认知",
    '独立判断': "自我效能感",
    '公开表达': "表达系统",
    '项目管理': "执行系统",
    '身体觉察': "具身认知",
}

VERIFIED_MECHANISM_LIBRARY = {
    '预期的可怕远大于实际': {
        "professional_name": "预期-体验差异",
        "source_system": "认知偏差",
        "summary": "主观预估中的危险和损失被系统性高估，实际体验往往显著轻于预期。",
    },
    '身体比大脑先知道答案': {
        "professional_name": "具身先验判断",
        "source_system": "具身认知",
        "summary": "身体反应会比语言分析更早给出方向判断，是高可信度的前置信号。",
    },
    '你的瞄准镜是准的': {
        "professional_name": "内在参照系校准",
        "source_system": "自我信任",
        "summary": "当评价标准回到自身参照系时，判断和行动精度显著提升。",
    },
    '主动表达需求不会伤害感情': {
        "professional_name": "需求表达安全性",
        "source_system": "关系边界",
        "summary": "被压抑的需求一旦被及时表达，关系并不会自动破裂，反而更容易建立真实连接。",
    },
    '凌晨高效': {
        "professional_name": "低噪声专注窗口",
        "source_system": "注意力节律",
        "summary": "在低打扰与明确截止的窗口中，系统更容易进入连续稳定的高产状态。",
    },
}

MONTHLY_TOPIC_LIBRARY = {
    '辩论赛中的"知道但说不出"现象': {
        "id": "mp01",
        "source_domain": "公开表达",
        "priority": "高优先级",
        "objective": "把“知道但说不出”从单次挫败转成可训练的表达对象。",
        "action": "围绕课堂发言、播客试录、模拟面试做固定频率口头输出。",
        "tracking_pattern": "表达加载延迟与气势不足",
        "topic_title": "表达加载问题",
    },
    "对物理/高阶理论的复杂关系": {
        "id": "mp02",
        "source_domain": "认知升级",
        "priority": "中高优先级",
        "objective": "把“高不可攀的神殿”重新拆解为可进入的学习路径。",
        "action": "挑一条理论线做低门槛切入，每周保留固定的入门记录。",
        "tracking_pattern": "知识权威焦虑",
        "topic_title": "高阶理论距离感",
    },
    "男性认同与集体站边的性别议题": {
        "id": "mp03",
        "source_domain": "关系结构",
        "priority": "中优先级",
        "objective": "继续识别“谁被默认站边”背后的权力结构判断。",
        "action": "把触发你强烈不适的性别场景单独记录，提炼重复机制。",
        "tracking_pattern": "权力结构识别",
        "topic_title": "性别与站边机制",
    },
    "身体的第三个维度": {
        "id": "mp04",
        "source_domain": "身体觉察",
        "priority": "中优先级",
        "objective": "继续扩展听觉之外的身体维度，让空间感和节律感进入觉察系统。",
        "action": "结合射箭、步行或语音记录，持续标注新的身体信号。",
        "tracking_pattern": "身体感知扩容",
        "topic_title": "第三个身体维度",
    },
    "一人公司身份与关系承诺的平衡": {
        "id": "mp05",
        "source_domain": "身份与关系",
        "priority": "高优先级",
        "objective": "让“一人公司”身份和真实连接同时存在，而不是互相抵消。",
        "action": "区分合作、陪伴、承诺三类关系，观察哪些连接会放大而不是侵蚀主体性。",
        "tracking_pattern": "主体性与连接平衡",
        "topic_title": "一人公司与连接",
    },
}

SUGGESTION_NORMALIZATION_LIBRARY = [
    {
        "normalized_key": "主动定规则_不等别人提需求",
        "title": "主动定规则，不等别人提需求",
        "keywords": ["不等老三提需求", "主动设计你想要的功能", "定规则", "48小时内给反馈", "护栏", "不是外包"],
        "related_patterns": ["p03", "p04"],
    },
    {
        "normalized_key": "允许休息_不把停顿当退步",
        "title": "允许停顿，不把休息当退步",
        "keywords": ["什么都不想做", "不去评判", "不用给它贴", "不做几天", "主动选择了这样子的一个状态", "放松"],
        "related_patterns": [],
    },
    {
        "normalized_key": "关系抽离观察_先不急着纠正",
        "title": "先抽离观察，不急着纠正关系",
        "keywords": ["抽出来", "观察再积累", "不需要急着做什么", "不用去纠正", "站在什么位置"],
        "related_patterns": ["p05"],
    },
    {
        "normalized_key": "射箭日志_记录身体反馈",
        "title": "用射箭日志记录身体反馈",
        "keywords": ["射箭前设定一个问题", "射完回来用语音录", "射箭日志", "射箭周卡期间的仪式化"],
        "related_patterns": [],
    },
    {
        "normalized_key": "用语音做表达训练",
        "title": "用语音做表达训练",
        "keywords": ["模拟面试", "录音", "说话来练", "播客试录", "口头输出", "开麦", "课堂发言"],
        "related_patterns": ["p04"],
    },
    {
        "normalized_key": "五个项目_寻找共同主线",
        "title": "完成五个项目并找出共同主线",
        "keywords": ["五个项目", "隐形的线", "横向对比分析", "真正想做的事"],
        "related_patterns": ["p03"],
    },
    {
        "normalized_key": "回看财务全景_对冲焦虑",
        "title": "回看财务全景表，对冲财务焦虑",
        "keywords": ["财务焦虑", "财务全景表", "花呗5万", "收入为0"],
        "related_patterns": ["p02"],
    },
    {
        "normalized_key": "记录自己判断正确的证据",
        "title": "记录“我原来就是对的”的证据",
        "keywords": ["我原来就是对的", "记一笔", "10条", "被 AI 或他人验证", "为什么不相信自己"],
        "related_patterns": ["p01"],
    },
    {
        "normalized_key": "更新身份标签_不再把自己叫小白",
        "title": "更新身份标签，不再把自己叫小白",
        "keywords": ["你不是小白", "三个月前的标签", "快速进入陌生领域并产出结果"],
        "related_patterns": [],
    },
    {
        "normalized_key": "高阶理论低门槛切入",
        "title": "为高阶理论设计低门槛切入",
        "keywords": ["高不可攀的神殿", "低门槛切入", "理论线", "入门记录"],
        "related_patterns": ["p07"],
    },
    {
        "normalized_key": "一人公司与连接的平衡",
        "title": "区分连接类型，平衡一人公司与关系承诺",
        "keywords": ["一人公司", "合作、陪伴、承诺", "侵蚀主体性"],
        "related_patterns": [],
    },
    {
        "normalized_key": "扩展身体维度觉察",
        "title": "继续标注新的身体维度",
        "keywords": ["身体的第三个维度", "空间感", "身体信号"],
        "related_patterns": [],
    },
]

HORIZON_ORDER = {"short": 0, "medium": 1, "long": 2}
PRIORITY_BY_HORIZON = {"short": "high", "medium": "medium", "long": "low"}
REMINDER_STATUS_ORDER = {"active": 0, "new": 1, "snoozed": 2, "done": 3, "dismissed": 4}

TENDAY_TRACKING_LIBRARY = {
    '我先帮别人，然后才轮到我': "自我优先顺序",
    '我知道答案，但我不敢相信': "自我信任",
    '凌晨出高产': "能量节律",
    'AI 是你的"外置大脑"，也是你的镜子': "AI 协作模式",
}

TENDAY_CAPABILITY_SCORE_MAP = {
    "自我评价": (2, 7),
    "边界感": (3, 8),
    "决策方式": (3, 8),
    "行动模式": (3, 7),
    "AI 使用": (4, 9),
    "社交姿态": (3, 8),
    "身体觉察": (3, 8),
}

TERM_HEATMAP_CATALOG = [
    {"term": "相变", "mapping": "状态不可逆迁移", "color": "#d97706"},
    {"term": "主体性", "mapping": "从被动者转向主体位置", "color": "#2563eb"},
    {"term": "边界", "mapping": "需求表达与关系护栏", "color": "#059669"},
    {"term": "瞄准镜", "mapping": "内在参照系校准", "color": "#b45309"},
    {"term": "外部确认", "mapping": "需要被外界证明才敢行动", "color": "#7c3aed"},
    {"term": "身体", "mapping": "具身信号先于理性判断", "color": "#dc2626"},
]

SOLAR_TERMS = [
    ("小寒", (1, 5)),
    ("大寒", (1, 20)),
    ("立春", (2, 4)),
    ("雨水", (2, 19)),
    ("惊蛰", (3, 6)),
    ("春分", (3, 21)),
    ("清明", (4, 5)),
    ("谷雨", (4, 20)),
    ("立夏", (5, 6)),
    ("小满", (5, 21)),
    ("芒种", (6, 6)),
    ("夏至", (6, 21)),
    ("小暑", (7, 7)),
    ("大暑", (7, 23)),
    ("立秋", (8, 8)),
    ("处暑", (8, 23)),
    ("白露", (9, 8)),
    ("秋分", (9, 23)),
    ("寒露", (10, 8)),
    ("霜降", (10, 24)),
    ("立冬", (11, 8)),
    ("小雪", (11, 22)),
    ("大雪", (12, 7)),
    ("冬至", (12, 22)),
]


class ResolvedConfig:
    def __init__(
        self,
        profile: str,
        vault_root: Path,
        paths: dict[str, Path],
        dashboard_sections: list[str],
        enums: dict[str, list[str]],
        pattern_status_normalization: dict[str, Any],
    ) -> None:
        self.profile = profile
        self.vault_root = vault_root
        self.paths = paths
        self.dashboard_sections = dashboard_sections
        self.enums = enums
        self.pattern_status_normalization = pattern_status_normalization


def load_raw_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get_available_profiles() -> list[str]:
    return list(load_raw_config()["profiles"].keys())


def load_config(profile_override: str | None = None) -> ResolvedConfig:
    raw = load_raw_config()
    profile = profile_override or os.environ.get("COGNITIVE_PROFILE") or raw["default_profile"]
    if profile not in raw["profiles"]:
        available = ", ".join(sorted(raw["profiles"].keys()))
        raise ValueError(f'Unknown profile "{profile}". Available profiles: {available}')
    profile_config = raw["profiles"][profile]
    vault_root = Path(profile_config["vault_root"])
    if not vault_root.is_absolute():
        vault_root = (WORKSPACE_ROOT / vault_root).resolve()

    paths = {name: vault_root / rel_path for name, rel_path in raw["paths"].items()}
    return ResolvedConfig(
        profile=profile,
        vault_root=vault_root,
        paths=paths,
        dashboard_sections=raw["dashboard"]["homepage_sections"],
        enums=raw["enums"],
        pattern_status_normalization=raw["pattern_status_normalization"],
    )


def get_default_vault_root() -> Path:
    return load_config().vault_root


ROOT = get_default_vault_root()


def require_path(path: Path, label: str, expect_dir: bool) -> None:
    if not path.exists():
        raise FileNotFoundError(f'Missing {label}: {path}')
    if expect_dir and not path.is_dir():
        raise NotADirectoryError(f'Expected directory for {label}: {path}')
    if not expect_dir and not path.is_file():
        raise FileNotFoundError(f'Expected file for {label}: {path}')


def collect_markdown_files(path: Path, label: str) -> list[Path]:
    require_path(path, label, expect_dir=True)
    return sorted(path.glob("*.md"))


def clean_inline(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = text.replace("**", "").replace("__", "")
    text = text.replace("“", '"').replace("”", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_block(text: str) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^>\s*", "", line)
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^[-*]\s+", "", line)
        line = re.sub(r"^\d+\.\s+", "", line)
        line = clean_inline(line)
        if line:
            lines.append(line)
    return "\n".join(lines).strip()


def excerpt(text: str, max_len: int = 180) -> str:
    plain = clean_block(text)
    if len(plain) <= max_len:
        return plain
    return plain[: max_len - 1].rstrip() + "…"


def parse_frontmatter_value(value: str) -> Any:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [clean_inline(part.strip().strip('"').strip("'")) for part in inner.split(",") if part.strip()]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return clean_inline(value.strip('"').strip("'"))


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text

    match = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not match:
        return {}, text

    data: dict[str, Any] = {}
    current_key: str | None = None
    block = match.group(1)
    for raw in block.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if current_key and stripped.startswith("- "):
            data.setdefault(current_key, []).append(clean_inline(stripped[2:]))
            continue
        current_key = None
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            data[key] = parse_frontmatter_value(value)
        else:
            data[key] = []
            current_key = key
    return data, text[match.end() :]


def split_by_level(text: str, level: int) -> list[tuple[str, str]]:
    pattern = re.compile(rf"^(#{{{level}}})\s+(.+)$", re.M)
    matches = list(pattern.finditer(text))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = clean_inline(match.group(2))
        sections.append((title, text[start:end].strip()))
    return sections


def find_section(sections: list[tuple[str, str]], keyword: str) -> str:
    for title, content in sections:
        if keyword in title:
            return content
    return ""


def parse_markdown_table(block: str) -> list[dict[str, str]]:
    lines = [line.strip() for line in block.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        return []
    headers = [clean_inline(cell) for cell in lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in lines[2:]:
        cells = [clean_inline(cell) for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        rows.append(dict(zip(headers, cells)))
    return rows


def parse_first_table(block: str) -> list[dict[str, str]]:
    table_lines: list[str] = []
    in_table = False
    for raw in block.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            table_lines.append(line)
            in_table = True
            continue
        if in_table:
            break
    if table_lines:
        rows = parse_markdown_table("\n".join(table_lines))
        if rows:
            return rows
    return []


def parse_bullets(block: str) -> list[str]:
    items: list[str] = []
    for raw in block.splitlines():
        stripped = raw.strip()
        if re.match(r"^[-*]\s+", stripped):
            items.append(clean_inline(re.sub(r"^[-*]\s+", "", stripped)))
        elif re.match(r"^\d+\.\s+", stripped):
            items.append(clean_inline(re.sub(r"^\d+\.\s+", "", stripped)))
    return items


def extract_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.M)
    return clean_inline(match.group(1)) if match else ""


def extract_updated_at(text: str) -> str:
    match = re.search(r"最后更新[:：]\s*([0-9]{4}-[0-9]{2}-[0-9]{2})", text)
    return match.group(1) if match else ""


def extract_full_date(text: str) -> str:
    patterns = [
        r"(\d{4})年(\d{1,2})月(\d{1,2})日",
        r"(\d{4})[-_/.](\d{1,2})[-_/.](\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            year, month, day = (int(part) for part in match.groups())
            return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def normalize_date(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def extract_dates(text: str, default_year: int | None = None) -> list[str]:
    results: list[str] = []

    def add(value: str) -> None:
        if value not in results:
            results.append(value)

    for match in re.finditer(r"(?<!\d)(\d{4})[.\-_/](\d{1,2})[.\-_/](\d{1,2})(?!\d)", text):
        add(normalize_date(int(match.group(1)), int(match.group(2)), int(match.group(3))))

    for match in re.finditer(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日", text):
        add(normalize_date(int(match.group(1)), int(match.group(2)), int(match.group(3))))

    if default_year is None:
        default_year = datetime.now().year

    for match in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})\s*[-—]\s*(\d{1,2})(?!\d)", text):
        month = int(match.group(1))
        add(normalize_date(default_year, month, int(match.group(2))))
        add(normalize_date(default_year, month, int(match.group(3))))

    for match in re.finditer(r"(?<!\d)(\d{1,2})/(\d{1,2})(?!\d)", text):
        add(normalize_date(default_year, int(match.group(1)), int(match.group(2))))

    for match in re.finditer(r"(?<!\d)(\d{1,2})月(\d{1,2})日", text):
        add(normalize_date(default_year, int(match.group(1)), int(match.group(2))))

    return results


def extract_first_date(text: str, default_year: int | None = None) -> str:
    dates = extract_dates(text, default_year)
    return dates[0] if dates else ""


def extract_last_date(text: str, default_year: int | None = None) -> str:
    dates = extract_dates(text, default_year)
    return dates[-1] if dates else ""


def short_label(text: str, max_len: int = 8) -> str:
    cleaned = clean_inline(text)
    cleaned = re.split(r"[，,（(]", cleaned)[0].strip()
    return cleaned[:max_len]


def split_arrow_steps(text: str) -> list[str]:
    return [clean_inline(part) for part in text.split("→") if clean_inline(part)]


def count_evidence_items(text: str) -> int:
    parts = [clean_inline(part) for part in re.split(r"[;；]", text) if clean_inline(part)]
    return len(parts) if parts else (1 if clean_inline(text) else 0)


def trim_text(text: str, max_len: int) -> str:
    cleaned = clean_inline(text)
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 1].rstrip() + "…"


def nullable(value: str) -> str | None:
    cleaned = clean_inline(value)
    return cleaned or None


def now_local() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def sentence_excerpt(text: str, max_len: int = 90) -> str:
    cleaned = clean_block(text)
    if not cleaned:
        return ""
    parts = re.split(r"[。！？!?]", cleaned)
    first = clean_inline(parts[0])
    if first:
        return trim_text(first, max_len)
    return trim_text(cleaned, max_len)


def split_semicolon_items(text: str) -> list[str]:
    return [clean_inline(part) for part in re.split(r"[;；]", text) if clean_inline(part)]


def contract_pattern_status(value: str) -> str:
    if value == "candidate":
        return "candidate"
    if value == "active":
        return "active"
    return "rewriting"


def label_for_belief_status(value: str) -> str:
    return {
        "established": "已确立",
        "in_progress": "进行中",
        "pending": "待形成",
    }.get(value, value)


def label_for_new_belief_status(value: str) -> str:
    return {
        "generated": "已生成",
        "pending": "待生成",
    }.get(value, value)


def trend_info(raw_status: str) -> tuple[str, str]:
    cleaned = clean_inline(raw_status)
    rising_tokens = ["强化", "全面爆发", "新发现", "新出现", "从隐性到显性", "新觉察"]
    falling_tokens = ["松动", "减弱", "缓解", "转向", "重塑", "改写", "挑战中", "行动中", "深度改写"]
    has_rising = any(token in cleaned for token in rising_tokens)
    has_falling = any(token in cleaned for token in falling_tokens)
    if has_rising and has_falling:
        return "flat", "波动"
    if has_falling:
        return "down", "下降"
    if has_rising:
        return "up", "上升"
    return "flat", "稳定"


def infer_pattern_confidence(contract_status: str, evidence_count: int) -> float:
    baseline = {"candidate": 0.62, "active": 0.78, "rewriting": 0.86}.get(contract_status, 0.75)
    return round(min(0.96, baseline + min(evidence_count, 4) * 0.02), 2)


def extract_prefixed_items(block: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"^\*\*(.+?)\*\*\s*(.*?)(?=^\*\*.+?\*\*\s*$|^\*\*.+?[:：].+?\*\*\s*$|\Z)", re.M | re.S)
    items: list[tuple[str, str]] = []
    for match in pattern.finditer(block):
        title = clean_inline(match.group(1)).rstrip("：:")
        inline_rest = clean_inline(match.group(2))
        if inline_rest.startswith("：") or inline_rest.startswith(":"):
            inline_rest = clean_inline(inline_rest[1:])
        body = clean_block(inline_rest)
        if title:
            items.append((title, body))
    return items


def extract_bold_heading(text: str) -> tuple[str, str]:
    match = re.match(r'^\*\*(.+?)\*\*\s*(.*)$', clean_inline(text))
    if match:
        return clean_inline(match.group(1)), clean_inline(match.group(2))
    return "", clean_inline(text)


def infer_season_window(date_value: str) -> str:
    if not date_value:
        return ""
    date_obj = datetime.strptime(date_value, "%Y-%m-%d")
    boundaries = [(name, datetime(date_obj.year, month, day)) for name, (month, day) in SOLAR_TERMS]
    current_name = boundaries[0][0]
    next_name = boundaries[1][0]
    for index, (name, boundary) in enumerate(boundaries):
        if date_obj >= boundary:
            current_name = name
            next_name = boundaries[(index + 1) % len(boundaries)][0]
        else:
            break
    return f"{current_name} → {next_name}"


def extract_year_month(text: str) -> str:
    match = re.search(r"(\d{4})[-_/年](\d{1,2})月?", text)
    if not match:
        return ""
    year = int(match.group(1))
    month = int(match.group(2))
    return f"{year:04d}-{month:02d}-01"


def extract_first_blockquote(block: str) -> str:
    for raw in block.splitlines():
        stripped = raw.strip()
        if stripped.startswith(">"):
            text = clean_inline(stripped.lstrip("> ").strip())
            text = re.sub(r"^(关键洞察)[:：]", "", text)
            return text.strip('"')
    return ""


def extract_named_quote(block: str, label: str) -> str:
    for raw in block.splitlines():
        stripped = raw.strip()
        if label not in stripped:
            continue
        text = clean_inline(stripped.lstrip("> ").strip())
        text = re.sub(rf"^{label}[:：]", "", text)
        return text.strip('"')
    return ""


def extract_tags(frontmatter: dict[str, Any]) -> list[str]:
    tags = frontmatter.get("tags", [])
    if isinstance(tags, list):
        return [clean_inline(str(tag)) for tag in tags if clean_inline(str(tag))]
    if isinstance(tags, str) and tags:
        return [clean_inline(part) for part in tags.split(",") if clean_inline(part)]
    return []


def resolve_report_type(path: Path, frontmatter: dict[str, Any], fallback: str) -> str:
    if frontmatter.get("type"):
        return str(frontmatter["type"])

    name = str(path)
    if "每日报告" in name:
        return "daily"
    if "十日总报告" in name:
        return "ten_day"
    if "月度汇总" in name:
        return "monthly"
    if path.name == "人生轨迹总览.md":
        return "growth"
    return fallback


def slugify(value: str) -> str:
    normalized = clean_inline(value)
    normalized = normalized.replace('"', "").replace("“", "").replace("”", "")
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", normalized).strip("_").lower()
    return slug or "item"


def normalize_pattern_name(value: str) -> str:
    return clean_inline(value).replace('"', "").replace("“", "").replace("”", "").strip()


def build_report_id(report_type: str, date_value: str, stem: str) -> str:
    if date_value:
        return f"{report_type}_{date_value.replace('-', '_')}"
    return f"{report_type}_{slugify(stem)}"


def infer_report_metadata(path: Path, fallback_type: str) -> tuple[dict[str, Any], str]:
    text = read_text(path)
    frontmatter, body = parse_frontmatter(text)
    report_type = resolve_report_type(path, frontmatter, fallback_type)
    heading = extract_heading(body)
    title = clean_inline(str(frontmatter.get("title") or heading or path.stem))
    tags = extract_tags(frontmatter)

    date_value = ""
    if frontmatter.get("date"):
        date_value = clean_inline(str(frontmatter["date"]))
    if not date_value:
        date_value = extract_full_date(title) or extract_full_date(path.stem)
    if not date_value and report_type == "monthly":
        date_value = extract_year_month(title) or extract_year_month(path.stem)
    if not date_value and report_type == "growth":
        date_value = extract_updated_at(body)

    metadata = {
        "id": build_report_id(report_type, date_value, path.stem),
        "type": report_type,
        "date": date_value,
        "title": title,
        "tags": tags,
        "source_path": str(path),
    }
    return metadata, body


def parse_period_label(label: str) -> tuple[str, str]:
    normalized = label.replace("—", "-").replace("–", "-")
    matches = list(re.finditer(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", normalized))
    if len(matches) >= 2:
        first = matches[0]
        second = matches[1]
        first_year = int(first.group(1))
        second_year = int(second.group(1) or first.group(1))
        start = f"{first_year:04d}-{int(first.group(2)):02d}-{int(first.group(3)):02d}"
        end = f"{second_year:04d}-{int(second.group(2)):02d}-{int(second.group(3)):02d}"
        return start, end

    slash_matches = list(re.finditer(r"(?:(\d{4})[-/])?(\d{1,2})/(\d{1,2})", normalized))
    if len(slash_matches) >= 2:
        first = slash_matches[0]
        second = slash_matches[1]
        first_year = int(first.group(1) or datetime.now().year)
        second_year = int(second.group(1) or first_year)
        start = f"{first_year:04d}-{int(first.group(2)):02d}-{int(first.group(3)):02d}"
        end = f"{second_year:04d}-{int(second.group(2)):02d}-{int(second.group(3)):02d}"
        return start, end

    return "", ""


def classify_shaping_moment(label: str, body: str) -> str:
    text = f"{label} {body}"
    if any(keyword in text for keyword in ["身体先于意识", "身体第一次压倒大脑", "离开郑州来杭州", "身体比大脑"]):
        return "身体决定"
    if any(keyword in text for keyword in ["主体性", "主角", "以我为中心", "完整"]):
        return "主体觉醒"
    if any(keyword in text for keyword in ["老板", "一人公司", "身份", "宣言", "向上而生"]):
        return "身份确立"
    if any(keyword in text for keyword in ["小声一点", "老板娘", "需求", "理发店", "受委屈"]):
        return "边界重塑"
    if any(keyword in text for keyword in ["亲密关系", "被接住", "妈妈", "亲戚", "姐姐买房", "关系"]):
        return "关系清理"
    if any(keyword in text for keyword in ["会议", "开麦", "播客", "推动进度", "主导", "能力"]):
        return "能力跃迁"
    return "自我觉察"


def parse_shaping_moments(block: str) -> list[dict[str, str]]:
    pattern = re.compile(r"^\*\*(\d{4}\.\d{2}\.\d{2})\s*\|\s*(.+?)\*\*\s*\n(.*?)(?=^\*\*\d{4}\.\d{2}\.\d{2}\s*\||\Z)", re.M | re.S)
    items: list[dict[str, str]] = []
    for match in pattern.finditer(block):
        date_value = extract_full_date(match.group(1))
        label = clean_inline(match.group(2))
        body = clean_block(match.group(3))
        items.append(
            {
                "date": date_value,
                "label": label,
                "category": classify_shaping_moment(label, body),
            }
        )
    return items


def parse_open_threads(block: str, watch_since: str) -> list[dict[str, str]]:
    pattern = re.compile(r"^\d+\.\s+\*\*(.+?)\*\*[:：]\s*(.*?)(?=^\d+\.\s+\*\*|\Z)", re.M | re.S)
    items: list[dict[str, str]] = []
    for index, match in enumerate(pattern.finditer(block), start=1):
        items.append(
            {
                "id": f"thread{index:02d}",
                "title": clean_inline(match.group(1)),
                "summary": trim_text(clean_block(match.group(2)), 50),
                "watchSince": watch_since,
            }
        )
    return items


def sanitize_quote_text(text: str, max_len: int = 40) -> str:
    cleaned = clean_inline(text)
    cleaned = cleaned.strip('"').strip("「").strip("」").strip("“").strip("”")
    cleaned = re.split(r"[—\-]{2,}|——", cleaned)[0].strip()
    return trim_text(cleaned, max_len)


def parse_monthly_quotes(block: str, default_year: int) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    pattern = re.compile(r'^\d+\.\s+\*\*([0-9/]+)\*\*\s+[\"「](.+?)[\"」]', re.M)
    for match in pattern.finditer(block):
        items.append(
            {
                "date": extract_first_date(match.group(1), default_year),
                "text": sanitize_quote_text(match.group(2)),
            }
        )
    return items


def parse_growth_quotes(block: str, default_year: int) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    pattern = re.compile(r'^\>\s+\*\*([0-9/]+)\*\*[:：][「"](.+?)[」"]', re.M)
    for match in pattern.finditer(block):
        items.append(
            {
                "date": extract_first_date(match.group(1), default_year),
                "text": sanitize_quote_text(match.group(2)),
            }
        )
    return items


def parse_verified_laws(block: str, default_year: int) -> list[dict[str, Any]]:
    pattern = re.compile(r"^\*\*(\d+)\.\s*(.+?)\*\*\s*\n(.*?)(?=^\*\*\d+\.\s*.+?\*\*\s*$|\Z)", re.M | re.S)
    items: list[dict[str, Any]] = []
    for index, match in enumerate(pattern.finditer(block), start=1):
        title = clean_inline(match.group(2))
        body = match.group(3)
        first_seen_match = re.search(r"首次发现[:：]\s*(.+)", body)
        verification_match = re.search(r"验证次数[:：]\s*(\d+)\+?", body)
        follow_match = re.search(r"后续验证[:：]\s*(.+)", body)
        physics_tags: list[str] = []
        if title.startswith("凌晨高效"):
            parts = title.split("：", 1)
            title = "凌晨高效"
            if len(parts) > 1:
                physics_tags = [clean_inline(part) for part in parts[1].split("+") if clean_inline(part)]
        elif "——" in title:
            title = clean_inline(title.split("——", 1)[0])

        verification_count = 0
        if verification_match:
            verification_count = int(verification_match.group(1))
        elif follow_match:
            verification_count = len([part for part in follow_match.group(1).split("、") if clean_inline(part)])

        items.append(
            {
                "id": f"law{index:02d}",
                "title": title,
                "verificationCount": verification_count,
                "firstSeen": extract_first_date(first_seen_match.group(1) if first_seen_match else "", default_year),
                "physicsTags": physics_tags,
            }
        )
    return items


def parse_daily_report(path: Path) -> dict[str, Any]:
    metadata, body = infer_report_metadata(path, "daily")
    level2 = split_by_level(body, 2)
    log_sections = split_by_level(find_section(level2, "日志整理"), 3)
    analysis_sections = split_by_level(find_section(level2, "多维度分析"), 3)
    feelings_block = find_section(log_sections, "今日感受")
    psychology_block = find_section(analysis_sections, "心理学分析")
    cbt_block = find_section(analysis_sections, "认知行为学")
    mystic_block = find_section(analysis_sections, "玄学分析")
    physics_block = find_section(analysis_sections, "物理学视角")
    advice_block = find_section(level2, "综合建议")
    blindspot = clean_block(find_section(level2, "认知盲区诊断"))
    advice = clean_block(advice_block)
    quote = extract_first_blockquote(find_section(level2, "今日值得被记住的一句话"))
    key_insight = extract_named_quote(feelings_block, "关键洞察") or extract_first_blockquote(feelings_block)
    summary = excerpt(key_insight or blindspot or advice or quote)

    return {
        **metadata,
        "summary": summary,
        "quote": quote,
        "key_insight": key_insight,
        "blindspot": excerpt(blindspot) if blindspot else "",
        "feelings_block": feelings_block,
        "psychology_block": psychology_block,
        "cbt_block": cbt_block,
        "mystic_block": mystic_block,
        "physics_block": physics_block,
        "advice_block": advice_block,
        "sort_date": metadata["date"],
    }


def parse_ten_day_report(path: Path) -> dict[str, Any]:
    metadata, body = infer_report_metadata(path, "ten_day")
    period_match = re.search(r"报告周期[:：]\s*([^\n]+)", body)
    period_label = clean_inline(period_match.group(1)) if period_match else metadata["title"]
    period_start, period_end = parse_period_label(period_label)
    level2 = split_by_level(body, 2)
    summary_block = find_section(level2, "五条主线") or find_section(level2, "主线提炼")
    timeline_table = parse_first_table(find_section(level2, "全景时间线"))
    pattern_sections = split_by_level(find_section(level2, "反复出现的模式"), 3)
    metrics_sections = split_by_level(find_section(level2, "数据与变化"), 3)
    energy_block = find_section(level2, "玄学视角")
    physics_block = find_section(level2, "物理学视角")
    advice_block = find_section(level2, "综合建议")
    capability_change_table = parse_first_table(find_section(metrics_sections, "关键能力的变化"))

    return {
        **metadata,
        "period_label": period_label,
        "period_start": period_start,
        "period_end": period_end,
        "summary": excerpt(summary_block),
        "timeline_table": timeline_table,
        "pattern_sections": pattern_sections,
        "emotion_block": find_section(metrics_sections, "情绪曲线"),
        "action_block": find_section(metrics_sections, "行动力曲线"),
        "capability_change_table": capability_change_table,
        "energy_block": energy_block,
        "physics_block": physics_block,
        "advice_block": advice_block,
        "sort_date": period_end or metadata["date"],
    }


def parse_monthly_summary(path: Path) -> dict[str, Any]:
    metadata, body = infer_report_metadata(path, "monthly")
    level2 = split_by_level(body, 2)
    beliefs_block = find_section(level2, "信念地图更新")
    belief_sections = split_by_level(beliefs_block, 3)
    updated_at = extract_updated_at(body)
    default_year = int((updated_at or metadata["date"] or datetime.now().strftime("%Y-%m-%d"))[:4])
    active_patterns = parse_first_table(find_section(level2, "活跃的模式追踪"))
    turning_points = parse_first_table(find_section(level2, "关键转折点"))
    open_threads = parse_open_threads(find_section(level2, "未解决的线索"), updated_at or metadata["date"])
    monthly_quotes = parse_monthly_quotes(find_section(level2, "本月金句"), default_year)

    return {
        **metadata,
        "updated_at": updated_at,
        "summary": excerpt(find_section(level2, "本月核心叙事"), 220),
        "active_patterns": active_patterns,
        "turning_points": turning_points,
        "open_threads": open_threads,
        "monthly_quotes": monthly_quotes,
        "beliefs_old": parse_bullets(find_section(belief_sections, "旧信念状态")),
        "beliefs_new": parse_bullets(find_section(belief_sections, "新信念状态")),
        "sort_date": updated_at or metadata["date"],
    }


def parse_growth_report(path: Path) -> dict[str, Any]:
    metadata, body = infer_report_metadata(path, "growth")
    level2 = split_by_level(body, 2)
    updated_at = extract_updated_at(body)
    default_year = int((updated_at or datetime.now().strftime("%Y-%m-%d"))[:4])

    return {
        **metadata,
        "updated_at": updated_at,
        "summary": excerpt(find_section(level2, "核心身份叙事"), 220),
        "belief_migrations": parse_first_table(find_section(level2, "信念演变地图")),
        "shaping_moments": parse_shaping_moments(find_section(level2, "塑造性时刻")),
        "capability_records": parse_first_table(find_section(level2, "能力成长记录")),
        "verified_laws": parse_verified_laws(find_section(level2, "反复验证的人生规律"), default_year),
        "important_quotes": parse_growth_quotes(find_section(level2, "你说过的最重要的话"), default_year),
        "sort_date": updated_at or metadata["date"],
    }


def sort_reports(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: item.get("sort_date") or item.get("date") or "")


def match_pattern_status(part: str, mapping: dict[str, list[str]]) -> str | None:
    cleaned = clean_inline(part)
    if not cleaned:
        return None
    for status, expressions in mapping.items():
        for expression in expressions:
            if expression in cleaned:
                return status
    return None


def normalize_pattern_status(raw_status: str, config: ResolvedConfig, warnings: list[str]) -> str:
    normalization = config.pattern_status_normalization
    mapping = normalization["mapping"]
    split_tokens = normalization["split_tokens"]
    default_status = normalization["default_status"]
    cleaned = clean_inline(raw_status)
    if not cleaned:
        warnings.append("pattern status empty, defaulted to active")
        return default_status

    split_pattern = "|".join(re.escape(token) for token in split_tokens)
    parts = [part.strip() for part in re.split(split_pattern, cleaned) if part.strip()]
    for part in reversed(parts or [cleaned]):
        matched = match_pattern_status(part, mapping)
        if matched:
            return matched

    warnings.append(f'unmapped pattern status "{cleaned}", defaulted to {default_status}')
    return default_status


def build_cognitive_state(
    daily_reports: list[dict[str, Any]],
    ten_day_reports: list[dict[str, Any]],
    monthly_summaries: list[dict[str, Any]],
    growth_report: dict[str, Any] | None,
    config: ResolvedConfig,
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    latest_month = monthly_summaries[-1] if monthly_summaries else None
    patterns: dict[str, dict[str, Any]] = {}

    if latest_month:
        for row in latest_month["active_patterns"]:
            name = normalize_pattern_name(row.get("模式名称", ""))
            if not name:
                continue
            status_raw = clean_inline(row.get("状态", ""))
            status = normalize_pattern_status(status_raw, config, warnings)
            key = slugify(name)
            patterns[key] = {
                "name": name,
                "status_raw": status_raw,
                "status": status,
                "latest_evidence": clean_inline(row.get("关键证据", "")),
                "source_report_id": latest_month["id"],
                "source_report_title": latest_month["title"],
                "source_report_path": latest_month["source_path"],
                "last_updated": latest_month.get("updated_at") or latest_month.get("date"),
            }

    counts = Counter(pattern["status"] for pattern in patterns.values())
    latest_daily = daily_reports[-1] if daily_reports else None
    latest_ten_day = ten_day_reports[-1] if ten_day_reports else None

    state = {
        "meta": {
            "profile": config.profile,
            "total_analyses": len(daily_reports) + len(ten_day_reports) + len(monthly_summaries),
            "last_updated": now_local().isoformat(timespec="seconds"),
            "latest_daily_report": latest_daily["source_path"] if latest_daily else "",
            "latest_ten_day_report": latest_ten_day["source_path"] if latest_ten_day else "",
            "latest_monthly_report": latest_month["source_path"] if latest_month else "",
            "latest_growth_report": growth_report["source_path"] if growth_report else "",
            "warning_count": len(warnings),
        },
        "patterns": patterns,
        "beliefs": {
            "loosening": latest_month["beliefs_old"] if latest_month else [],
            "growing": latest_month["beliefs_new"] if latest_month else [],
        },
        "emotional_baseline": {
            "latest_period": latest_ten_day["period_label"] if latest_ten_day else "",
            "weekly_snapshots": [],
        },
        "identity_narrative": growth_report["summary"] if growth_report else "",
        "metrics": {
            "pattern_count": len(patterns),
            "candidate_count": counts["candidate"],
            "active_count": counts["active"],
            "aware_count": counts["aware"],
            "loosening_count": counts["loosening"],
            "rewriting_count": counts["rewriting"],
            "dormant_count": counts["dormant"],
        },
    }
    return state, warnings


def build_report_index(
    daily_reports: list[dict[str, Any]],
    ten_day_reports: list[dict[str, Any]],
    monthly_summaries: list[dict[str, Any]],
    growth_report: dict[str, Any] | None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for report in [*daily_reports, *ten_day_reports, *monthly_summaries]:
        items.append(
            {
                "id": report["id"],
                "type": report["type"],
                "date": report.get("sort_date") or report.get("date") or "",
                "title": report["title"],
                "summary": report["summary"],
                "source_path": report["source_path"],
                "tags": report.get("tags", []),
            }
        )
    if growth_report:
        items.append(
            {
                "id": growth_report["id"],
                "type": growth_report["type"],
                "date": growth_report.get("sort_date") or growth_report.get("date") or "",
                "title": growth_report["title"],
                "summary": growth_report["summary"],
                "source_path": growth_report["source_path"],
                "tags": growth_report.get("tags", []),
            }
        )

    items = sorted(items, key=lambda item: item["date"])
    return {"generated_at": now_local().isoformat(timespec="seconds"), "items": items}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def normalize_display_text(value: str) -> str:
    return clean_inline(value).strip('"').strip("“").strip("”")


def trajectory_event_count(first_seen: str, trajectory: str) -> int:
    date_count = len(extract_dates(f"{first_seen} {trajectory}"))
    step_count = len(split_arrow_steps(trajectory))
    return max(1, date_count + step_count)


def build_capability_radar(growth_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not growth_report:
        return []
    records = growth_report.get("capability_records", [])
    if not records:
        return []
    counts = [
        trajectory_event_count(clean_inline(row.get("首次出现", "")), clean_inline(row.get("成长轨迹", "")))
        for row in records
    ]
    max_count = max(counts) if counts else 1
    items: list[dict[str, Any]] = []
    for row, count in zip(records, counts):
        score = max(1, min(10, round((count / max_count) * 10)))
        current_state = row.get("当前状态（3月末）") or row.get("当前状态") or ""
        items.append(
            {
                "name": clean_inline(row.get("能力", "")),
                "score": score,
                "scoreMax": 10,
                "trajectoryEventCount": count,
                "currentStateLabel": short_label(current_state),
            }
        )
    return items


def build_verified_law_cards(growth_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not growth_report:
        return []
    return growth_report.get("verified_laws", [])

def build_quote_pool(latest_month: dict[str, Any] | None, growth_report: dict[str, Any] | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in [
        *(latest_month.get("monthly_quotes", []) if latest_month else []),
        *(growth_report.get("important_quotes", []) if growth_report else []),
    ]:
        key = (source.get("date", ""), source.get("text", ""))
        if key in seen:
            continue
        seen.add(key)
        items.append({"text": source.get("text", ""), "date": source.get("date", "")})
    return sorted(items, key=lambda item: item["date"])


def build_activity_density(
    latest_month: dict[str, Any] | None,
    growth_report: dict[str, Any] | None,
    reference_date: datetime,
) -> list[dict[str, Any]]:
    start_date = reference_date.date() - timedelta(days=29)
    event_map: dict[str, set[str]] = {}

    def add_event(date_value: str, event_key: str) -> None:
        if not date_value:
            return
        try:
            date_obj = datetime.strptime(date_value, "%Y-%m-%d").date()
        except ValueError:
            return
        if not (start_date <= date_obj <= reference_date.date()):
            return
        event_map.setdefault(date_value, set()).add(event_key)

    if growth_report:
        for moment in growth_report.get("shaping_moments", []):
            add_event(moment.get("date", ""), f"shape:{slugify(moment.get('label', ''))}")

    if latest_month:
        default_year = int((latest_month.get("updated_at") or latest_month.get("date") or "2026-01-01")[:4])
        for row in latest_month.get("turning_points", []):
            label = clean_inline(row.get("转折点", "")).split("：", 1)[0].split(":", 1)[0]
            add_event(extract_first_date(row.get("日期", ""), default_year), f"turn:{slugify(label)}")
        for row in latest_month.get("active_patterns", []):
            name = normalize_pattern_name(row.get("模式名称", ""))
            for date_value in extract_dates(row.get("关键证据", ""), default_year):
                add_event(date_value, f"pattern:{slugify(name)}:{date_value}")

    items: list[dict[str, Any]] = []
    for offset in range(30):
        day = start_date + timedelta(days=offset)
        day_key = day.strftime("%Y-%m-%d")
        items.append({"date": day_key, "count": len(event_map.get(day_key, set()))})
    return items


def build_latest_daily_extension(latest_daily: dict[str, Any] | None) -> dict[str, Any] | None:
    if not latest_daily:
        return None
    return {
        "title": latest_daily.get("title"),
        "date": latest_daily.get("date"),
        "summary": latest_daily.get("summary"),
        "quote": latest_daily.get("quote") or latest_daily.get("key_insight"),
        "source_path": latest_daily.get("source_path"),
    }


def build_stage_report_extension(
    latest_ten_day: dict[str, Any] | None,
    latest_month: dict[str, Any] | None,
    growth_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    reports = [
        ("最新阶段报告", latest_ten_day),
        ("最新月度汇总", latest_month),
        ("成长轨迹总览", growth_report),
    ]
    items: list[dict[str, Any]] = []
    for label, report in reports:
        if not report:
            continue
        items.append(
            {
                "label": label,
                "title": report.get("title"),
                "summary": report.get("summary"),
                "source_path": report.get("source_path"),
            }
        )
    return items


def build_open_threads_extension(latest_month: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not latest_month:
        return []
    items: list[dict[str, Any]] = []
    for thread in latest_month.get("open_threads", []):
        metadata = MONTHLY_TOPIC_LIBRARY.get(thread.get("title", ""))
        items.append(
            {
                "id": thread.get("id"),
                "title": thread.get("title"),
                "summary": thread.get("summary"),
                "watch_since": thread.get("watchSince"),
                "source_system": metadata.get("source_domain", "持续观察") if metadata else "持续观察",
            }
        )
    return items


def home_pattern_entry(
    index: int,
    row: dict[str, Any],
    pattern: dict[str, Any],
    default_year: int,
) -> dict[str, Any]:
    raw_name = normalize_pattern_name(row.get("模式名称", ""))
    metadata = PATTERN_LIBRARY.get(raw_name, {})
    evidence = clean_inline(row.get("关键证据", ""))
    evidence_count = count_evidence_items(evidence)
    contract_status = contract_pattern_status(pattern.get("status", "active"))
    trigger_trend, trigger_trend_label = trend_info(row.get("状态", ""))
    first_seen = extract_first_date(evidence, default_year) or pattern.get("last_updated") or ""
    return {
        "id": metadata.get("id", f"p{index:02d}"),
        "professional_name": metadata.get("professional_name", raw_name),
        "pattern_type": metadata.get("pattern_type", "待补充"),
        "source_system": metadata.get("source_system", "待补充"),
        "status": contract_status,
        "status_label": status_label(contract_status),
        "confidence": infer_pattern_confidence(contract_status, evidence_count),
        "evidence_count": evidence_count,
        "trigger_trend": trigger_trend,
        "trigger_trend_label": trigger_trend_label,
        "summary": metadata.get("summary", sentence_excerpt(evidence, 60)),
        "rewrite_target": metadata.get("rewrite_target"),
        "first_seen": first_seen,
        "last_updated": pattern.get("last_updated") or first_seen,
        "raw_name": raw_name,
        "raw_status": clean_inline(row.get("状态", "")),
        "source_path": pattern.get("source_report_path"),
        "latest_evidence": evidence,
        "source_report_title": pattern.get("source_report_title"),
        "source_report_id": pattern.get("source_report_id"),
    }


def build_home_patterns(cognitive_state: dict[str, Any], latest_month: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not latest_month:
        return []
    default_year = int((latest_month.get("updated_at") or latest_month.get("date") or "2026-01-01")[:4])
    items: list[dict[str, Any]] = []
    for index, row in enumerate(latest_month.get("active_patterns", []), start=1):
        raw_name = normalize_pattern_name(row.get("模式名称", ""))
        if not raw_name:
            continue
        pattern = cognitive_state["patterns"].get(slugify(raw_name), {})
        items.append(home_pattern_entry(index, row, pattern, default_year))
    return items


def build_home_belief_migrations(growth_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not growth_report:
        return []
    default_year = int((growth_report.get("updated_at") or "2026-01-01")[:4])
    items: list[dict[str, Any]] = []
    for index, row in enumerate(growth_report.get("belief_migrations", []), start=1):
        old_belief = normalize_display_text(row.get("旧信念", ""))
        new_belief_raw = normalize_display_text(row.get("替代信念", ""))
        new_belief = "" if "尚未形成替代" in new_belief_raw else new_belief_raw
        loosening_cell = clean_inline(row.get("松动时间", ""))
        established_cell = clean_inline(row.get("确立时间", ""))
        if "尚未确立" in established_cell or not new_belief:
            status = "pending"
            established_date = None
        elif "进行中" in established_cell:
            status = "in_progress"
            established_date = nullable(extract_last_date(established_cell, default_year))
        else:
            status = "established"
            established_date = nullable(extract_last_date(established_cell, default_year))
        new_belief_status = "generated" if new_belief else "pending"
        metadata = BELIEF_DOMAIN_LIBRARY.get(old_belief, {})
        items.append(
            {
                "id": metadata.get("id", f"b{index:02d}"),
                "domain": metadata.get("domain", "待补充"),
                "source_system": metadata.get("source_system", "待补充"),
                "status": status,
                "status_label": label_for_belief_status(status),
                "new_belief_status": new_belief_status,
                "new_belief_status_label": label_for_new_belief_status(new_belief_status),
                "loosening_date": nullable(extract_first_date(loosening_cell, default_year)),
                "established_date": established_date,
                "old_belief": old_belief or None,
                "new_belief": new_belief or None,
            }
        )
    return items


def build_home_capabilities(growth_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    radar = build_capability_radar(growth_report)
    items: list[dict[str, Any]] = []
    for entry in radar:
        name = clean_inline(entry["name"])
        items.append(
            {
                "name": name,
                "score": entry["score"],
                "max": entry["scoreMax"],
                "state_label": entry["currentStateLabel"],
                "source_system": CAPABILITY_SOURCE_LIBRARY.get(name, "待补充"),
                "events": entry["trajectoryEventCount"],
            }
        )
    return items


def normalized_law_key(title: str) -> str:
    for key in VERIFIED_MECHANISM_LIBRARY:
        if key in title:
            return key
    return title


def build_home_verified_mechanisms(growth_report: dict[str, Any] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for law in build_verified_law_cards(growth_report):
        raw_title = clean_inline(law.get("title", ""))
        metadata = VERIFIED_MECHANISM_LIBRARY.get(normalized_law_key(raw_title), {})
        items.append(
            {
                "id": law.get("id"),
                "professional_name": metadata.get("professional_name", raw_title),
                "source_system": metadata.get("source_system", "待补充"),
                "raw_title": raw_title,
                "summary": metadata.get("summary", sentence_excerpt(raw_title, 50)),
                "verification_count": law.get("verificationCount", 0),
                "first_seen": law.get("firstSeen"),
                "physics_tags": law.get("physicsTags", []),
            }
        )
    return items


def build_library_stats(latest_month: dict[str, Any] | None, growth_report: dict[str, Any] | None) -> dict[str, int]:
    quote_count = len(build_quote_pool(latest_month, growth_report))
    theme_count = len(latest_month.get("open_threads", [])) if latest_month else 0
    insight_count = (
        len(growth_report.get("shaping_moments", [])) if growth_report else 0
    ) + (
        len(growth_report.get("verified_laws", [])) if growth_report else 0
    ) + (
        len(latest_month.get("active_patterns", [])) if latest_month else 0
    ) + (
        len(latest_month.get("turning_points", [])) if latest_month else 0
    )
    return {
        "quote_count": quote_count,
        "theme_count": theme_count,
        "insight_count": insight_count,
    }


def build_home_page(
    generated_at: datetime,
    cognitive_state: dict[str, Any],
    latest_month: dict[str, Any] | None,
    growth_report: dict[str, Any] | None,
    latest_daily: dict[str, Any] | None,
    latest_ten_day: dict[str, Any] | None,
    reminders: dict[str, Any],
) -> dict[str, Any]:
    return {
        "page_type": "home",
        "last_updated": generated_at.isoformat(timespec="seconds"),
        "patterns": build_home_patterns(cognitive_state, latest_month),
        "belief_migrations": build_home_belief_migrations(growth_report),
        "capabilities": build_home_capabilities(growth_report),
        "verified_mechanisms": build_home_verified_mechanisms(growth_report),
        "library_stats": build_library_stats(latest_month, growth_report),
        "identity_narrative": cognitive_state.get("identity_narrative"),
        "latest_daily": build_latest_daily_extension(latest_daily),
        "latest_stage_reports": build_stage_report_extension(latest_ten_day, latest_month, growth_report),
        "activity_density": build_activity_density(latest_month, growth_report, generated_at),
        "shaping_moments": growth_report.get("shaping_moments", []) if growth_report else [],
        "open_threads": build_open_threads_extension(latest_month),
        "quote_pool": build_quote_pool(latest_month, growth_report),
        "active_reminders": build_home_active_reminders(reminders),
    }


def build_mystic_focus(daily_report: dict[str, Any]) -> list[dict[str, Any]]:
    block = daily_report.get("mystic_block", "")
    if not block:
        return []
    season_window = infer_season_window(daily_report.get("date", ""))
    items: list[dict[str, Any]] = [
        {
            "id": "m01",
            "source_system": "节气参考",
            "title": f"{season_window.split(' → ')[0]}窗口" if season_window else "节律窗口",
            "summary": sentence_excerpt(block, 70),
            "current_signal": season_window or "正在做内在归档",
            "marker": "清理陈旧 · 回收能量",
            "priority": 1,
        }
    ]
    if "海底轮" in block:
        items.append(
            {
                "id": "m02",
                "source_system": "脉轮系统",
                "title": "海底轮回落",
                "summary": "系统正在回到接地与安全感层面，优先做休息和能量收束，而不是继续外冲。",
                "current_signal": "需要接地而不是继续加速",
                "marker": "根部修复",
                "priority": 2,
            }
        )
    if "能量回收" in block or "收回来" in block:
        items.append(
            {
                "id": "m03",
                "source_system": "能量回收",
                "title": "关系场清理",
                "summary": "把在关系里流出去的注意力和情绪能量收回到自己身上，再进入下一轮判断。",
                "current_signal": "先收束，再回应",
                "marker": "边界回收",
                "priority": 3,
            }
        )
    return items


def build_psychology_analysis(daily_report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, (title, body) in enumerate(extract_prefixed_items(daily_report.get("psychology_block", "")), start=1):
        source_system = "创伤心理学"
        if "依恋" in title or "关系" in title:
            source_system = "依恋理论"
        items.append(
            {
                "id": f"psy{index:02d}",
                "source_system": source_system,
                "title": title,
                "highlight": sentence_excerpt(body, 36),
                "summary": trim_text(body, 110),
            }
        )
    if items:
        return items
    block = daily_report.get("psychology_block", "")
    if not block:
        return []
    return [
        {
            "id": "psy01",
            "source_system": "创伤心理学",
            "title": "心理学分析",
            "highlight": sentence_excerpt(block, 36),
            "summary": trim_text(block, 110),
        }
    ]


def build_cbt_event_analysis(daily_report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for index, (title, body) in enumerate(extract_prefixed_items(daily_report.get("cbt_block", "")), start=1):
        source_system = "CBT 自动思维链"
        if "运营系统" in title or "权力游戏" in title:
            source_system = "协作结构"
        if "李荣荣" in title:
            source_system = "人际权力结构"
        items.append(
            {
                "id": f"cbt{index:02d}",
                "source_system": source_system,
                "title": title,
                "highlight": sentence_excerpt(body, 36),
                "summary": trim_text(body, 120),
            }
        )
    return items


def excerpt_around_keyword(block: str, keyword: str, max_len: int = 90) -> str:
    cleaned = clean_block(block)
    if keyword not in cleaned:
        return trim_text(cleaned, max_len)
    index = cleaned.find(keyword)
    start = max(0, index - 16)
    end = min(len(cleaned), index + max_len)
    return trim_text(cleaned[start:end], max_len)


def build_physics_mirror(daily_report: dict[str, Any]) -> list[dict[str, Any]]:
    block = daily_report.get("physics_block", "")
    if not block:
        return []
    items: list[dict[str, Any]] = []
    if "阻尼振荡" in block:
        items.append(
            {
                "term": "阻尼振荡",
                "thesis": "高峰之后的不动，不一定是停滞，可能是系统在把势能内化为新的基线。",
                "summary": excerpt_around_keyword(block, "阻尼振荡", 86),
                "display_level": "secondary",
            }
        )
    if "负反馈调节器" in block:
        items.append(
            {
                "term": "负反馈调节器",
                "thesis": "你过去一直在替关系系统自动纠偏，退出之后系统的真实结构才暴露出来。",
                "summary": excerpt_around_keyword(block, "负反馈调节器", 86),
                "display_level": "secondary",
            }
        )
    if "表面张力" in block or "浮萍" in block:
        items.append(
            {
                "term": "表面张力",
                "thesis": "跟随环境流动并不等于被同化，系统仍然可以保持自己的边界和惯性。",
                "summary": excerpt_around_keyword(block, "浮萍", 86),
                "display_level": "secondary",
            }
        )
    return items or [
        {
            "term": "系统回摆",
            "thesis": sentence_excerpt(block, 40),
            "summary": trim_text(block, 100),
            "display_level": "secondary",
        }
    ]


def build_daily_actions(daily_report: dict[str, Any]) -> list[dict[str, Any]]:
    block = daily_report.get("advice_block", "")
    pattern = re.compile(r'^\-\s+\*\*(.+?)\*\*[:：]\s*(.+)$', re.M)
    items: list[dict[str, Any]] = []
    for index, match in enumerate(pattern.finditer(block), start=1):
        title = clean_inline(match.group(1)).replace("关于", "")
        detail = clean_inline(match.group(2))
        parts = re.split(r"[。；]", detail, maxsplit=1)
        action = clean_inline(parts[0])
        note = clean_inline(parts[1]) if len(parts) > 1 else action
        items.append(
            {
                "id": f"ad{index:02d}",
                "title": title,
                "action": action,
                "note": trim_text(note or detail, 60),
            }
        )
    return items


def infer_horizon(text: str, source_type: str) -> str:
    cleaned = clean_inline(text)
    if any(token in cleaned for token in ["短期", "本周", "今晚", "今天", "这周"]):
        return "short"
    if any(token in cleaned for token in ["中期", "本月", "这个月", "十五天", "4月需要关注", "接下来"]):
        return "medium"
    if any(token in cleaned for token in ["长期", "一直", "长期（", "关于自我认知", "需要一直带着"]):
        return "long"
    return {"daily": "short", "ten_day": "medium", "monthly": "long"}.get(source_type, "medium")


def normalize_suggestion_identity(title: str, summary: str) -> dict[str, Any]:
    text = f"{clean_inline(title)} {clean_inline(summary)}"
    for entry in SUGGESTION_NORMALIZATION_LIBRARY:
        if any(keyword in text for keyword in entry["keywords"]):
            return {
                "normalized_key": entry["normalized_key"],
                "canonical_title": entry["title"],
                "related_patterns": entry["related_patterns"],
            }
    fallback_key = clean_inline(title).replace('"', "").replace("“", "").replace("”", "")
    return {
        "normalized_key": slugify(fallback_key),
        "canonical_title": trim_text(clean_inline(title), 24),
        "related_patterns": [],
    }


def build_suggestion_candidate(
    *,
    report: dict[str, Any],
    source_type: str,
    title: str,
    summary: str,
    horizon: str,
    related_patterns: list[str] | None = None,
) -> dict[str, Any]:
    identity = normalize_suggestion_identity(title, summary)
    patterns = identity["related_patterns"] if related_patterns is None else related_patterns
    return {
        "normalized_key": identity["normalized_key"],
        "canonical_title": identity["canonical_title"],
        "title": clean_inline(title),
        "summary": trim_text(summary, 90),
        "horizon": horizon,
        "priority": PRIORITY_BY_HORIZON[horizon],
        "source_report": Path(report["source_path"]).name,
        "source_report_id": report["id"],
        "source_report_path": report["source_path"],
        "source_type": source_type,
        "date": report.get("sort_date") or report.get("date") or "",
        "related_patterns": patterns,
    }


def extract_daily_suggestions(daily_report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current_horizon = "short"
    for raw in daily_report.get("advice_block", "").splitlines():
        line = raw.strip()
        if not line:
            continue
        heading_match = re.match(r'^\*\*(.+?)\*\*$', line)
        if heading_match:
            current_horizon = infer_horizon(heading_match.group(1), "daily")
            continue
        item_match = re.match(r'^-\s+\*\*(.+?)\*\*[:：]\s*(.+)$', line)
        if not item_match:
            continue
        items.append(
            build_suggestion_candidate(
                report=daily_report,
                source_type="daily",
                title=item_match.group(1),
                summary=clean_inline(item_match.group(2)),
                horizon=current_horizon,
            )
        )
    return items


def extract_tenday_suggestions(ten_day_report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for section_title, content in split_by_level(ten_day_report.get("advice_block", ""), 3):
        horizon = infer_horizon(section_title, "ten_day")
        pattern = re.compile(r'^\d+\.\s+\*\*(.+?)\*\*[：:]?\s*(.*?)(?=^\d+\.\s+\*\*|\Z)', re.M | re.S)
        for match in pattern.finditer(content):
            items.append(
                build_suggestion_candidate(
                    report=ten_day_report,
                    source_type="ten_day",
                    title=match.group(1),
                    summary=clean_block(match.group(2)),
                    horizon=horizon,
                )
            )
    return items


def extract_monthly_suggestions(monthly_summary: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for thread in monthly_summary.get("open_threads", []):
        metadata = MONTHLY_TOPIC_LIBRARY.get(thread.get("title", ""))
        if not metadata:
            continue
        items.append(
            build_suggestion_candidate(
                report=monthly_summary,
                source_type="monthly",
                title=metadata["topic_title"],
                summary=metadata["action"],
                horizon="medium",
            )
        )
    return items


def collect_suggestion_candidates(
    daily_reports: list[dict[str, Any]],
    ten_day_reports: list[dict[str, Any]],
    monthly_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for report in daily_reports:
        items.extend(extract_daily_suggestions(report))
    for report in ten_day_reports:
        items.extend(extract_tenday_suggestions(report))
    for report in monthly_summaries:
        items.extend(extract_monthly_suggestions(report))
    return sorted(items, key=lambda item: (item["date"], item["source_report_id"], item["normalized_key"]))


def build_suggestion_index(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        group = groups.setdefault(
            candidate["normalized_key"],
            {
                "normalized_key": candidate["normalized_key"],
                "title": candidate["canonical_title"] or candidate["title"],
                "count": 0,
                "first_seen": candidate["date"],
                "last_seen": candidate["date"],
                "report_refs": [],
                "related_patterns": [],
                "latest_status": "new",
                "latest_horizon": candidate["horizon"],
                "source_types": [],
                "occurrences": [],
            },
        )
        group["count"] += 1
        if candidate["date"] and (not group["first_seen"] or candidate["date"] < group["first_seen"]):
            group["first_seen"] = candidate["date"]
        if candidate["date"] and (not group["last_seen"] or candidate["date"] > group["last_seen"]):
            group["last_seen"] = candidate["date"]
        if candidate["source_report_id"] not in group["report_refs"]:
            group["report_refs"].append(candidate["source_report_id"])
        for pattern in candidate["related_patterns"]:
            if pattern not in group["related_patterns"]:
                group["related_patterns"].append(pattern)
        if candidate["source_type"] not in group["source_types"]:
            group["source_types"].append(candidate["source_type"])
        if HORIZON_ORDER[candidate["horizon"]] < HORIZON_ORDER[group["latest_horizon"]]:
            group["latest_horizon"] = candidate["horizon"]
        group["occurrences"].append(
            {
                "title": candidate["title"],
                "summary": candidate["summary"],
                "source_report": candidate["source_report"],
                "source_report_id": candidate["source_report_id"],
                "source_type": candidate["source_type"],
                "date": candidate["date"],
                "horizon": candidate["horizon"],
            }
        )

    items = sorted(groups.values(), key=lambda item: (-item["count"], item["first_seen"], item["normalized_key"]))
    return {"generated_at": now_local().isoformat(timespec="seconds"), "items": items}


def load_existing_state_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"generated_at": None, "items": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"generated_at": None, "items": []}


def derive_suggestion_status(existing_item: dict[str, Any] | None, item: dict[str, Any], generated_at: datetime) -> tuple[str, str | None, str | None]:
    baseline_status = "active" if item["count"] >= 2 else "new"
    if not existing_item:
        return baseline_status, None, None

    status = existing_item.get("status", baseline_status)
    done_at = existing_item.get("done_at")
    snooze_until = existing_item.get("snooze_until")

    if status == "snoozed" and snooze_until:
        try:
            if datetime.fromisoformat(snooze_until) <= generated_at:
                return baseline_status, done_at, None
        except ValueError:
            return baseline_status, done_at, None

    if status in {"done", "dismissed"} and done_at:
        if item["last_seen"] and item["last_seen"] > done_at[:10]:
            return baseline_status, done_at, None

    if status == "new" and item["count"] >= 2:
        return "active", done_at, snooze_until
    return status, done_at, snooze_until


def build_reminders(
    suggestion_index: dict[str, Any],
    config: ResolvedConfig,
    generated_at: datetime,
) -> dict[str, Any]:
    existing = load_existing_state_file(config.paths["reminders"])
    existing_by_key = {item.get("normalized_key"): item for item in existing.get("items", []) if item.get("normalized_key")}
    items: list[dict[str, Any]] = []

    for suggestion in suggestion_index.get("items", []):
        latest = sorted(suggestion.get("occurrences", []), key=lambda occ: occ.get("date") or "")[-1]
        existing_item = existing_by_key.get(suggestion["normalized_key"])
        status, done_at, snooze_until = derive_suggestion_status(existing_item, suggestion, generated_at)
        created_at = existing_item.get("created_at") if existing_item else generated_at.isoformat(timespec="seconds")
        last_pushed_at = existing_item.get("last_pushed_at") if existing_item else None
        reminder = {
            "id": existing_item.get("id") if existing_item else f"r_{slugify(suggestion['normalized_key'])}",
            "normalized_key": suggestion["normalized_key"],
            "source_report": latest.get("source_report"),
            "source_type": latest.get("source_type"),
            "horizon": suggestion["latest_horizon"],
            "title": suggestion["title"],
            "summary": latest.get("summary"),
            "status": status,
            "priority": PRIORITY_BY_HORIZON[suggestion["latest_horizon"]],
            "channel": ["dashboard"],
            "count": suggestion["count"],
            "report_refs": suggestion["report_refs"],
            "related_patterns": suggestion["related_patterns"],
            "created_at": created_at,
            "updated_at": generated_at.isoformat(timespec="seconds"),
            "last_seen_at": suggestion["last_seen"],
            "last_pushed_at": last_pushed_at,
            "done_at": done_at,
            "snooze_until": snooze_until,
        }
        items.append(reminder)

    items.sort(
        key=lambda item: (
            REMINDER_STATUS_ORDER.get(item["status"], 9),
            HORIZON_ORDER.get(item["horizon"], 9),
            -(item.get("count") or 0),
            item.get("title") or "",
        )
    )
    return {"generated_at": generated_at.isoformat(timespec="seconds"), "items": items}


def attach_suggestion_statuses(suggestion_index: dict[str, Any], reminders: dict[str, Any]) -> dict[str, Any]:
    reminder_by_key = {item["normalized_key"]: item for item in reminders.get("items", [])}
    for item in suggestion_index.get("items", []):
        reminder = reminder_by_key.get(item["normalized_key"])
        item["latest_status"] = reminder.get("status", "new") if reminder else "new"
    return suggestion_index


def build_home_active_reminders(reminders: dict[str, Any]) -> list[dict[str, Any]]:
    active = [item for item in reminders.get("items", []) if item.get("status") == "active"]
    fallback = [item for item in reminders.get("items", []) if item.get("status") == "new"]
    visible = (active or fallback)[:2]
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "summary": item["summary"],
            "horizon": item["horizon"],
            "priority": item["priority"],
            "status": item["status"],
        }
        for item in visible
    ]


def build_term_heatmap(
    daily_reports: list[dict[str, Any]],
    ten_day_reports: list[dict[str, Any]],
    monthly_summaries: list[dict[str, Any]],
    growth_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    report_paths = [
        Path(report["source_path"])
        for report in [*daily_reports, *ten_day_reports, *monthly_summaries, *([growth_report] if growth_report else [])]
        if report and report.get("source_path")
    ]
    corpus = [read_text(path) for path in report_paths if path.exists()]
    total = len(corpus) or 1
    items: list[dict[str, Any]] = []
    for entry in TERM_HEATMAP_CATALOG:
        count = sum(1 for text in corpus if entry["term"] in text)
        items.append(
            {
                "term": entry["term"],
                "count": count,
                "total": total,
                "mapping": entry["mapping"],
                "color": entry["color"],
            }
        )
    return items


def build_daily_report_page(
    generated_at: datetime,
    daily_report: dict[str, Any] | None,
    daily_reports: list[dict[str, Any]],
    ten_day_reports: list[dict[str, Any]],
    monthly_summaries: list[dict[str, Any]],
    growth_report: dict[str, Any] | None,
) -> dict[str, Any]:
    if not daily_report:
        return {
            "page_type": "daily_report",
            "date": None,
            "title": None,
            "season_window": None,
            "last_updated": generated_at.isoformat(timespec="seconds"),
            "mystic_focus": [],
            "psychology_analysis": [],
            "cbt_event_analysis": [],
            "physics_mirror": [],
            "daily_actions": [],
            "term_heatmap": [],
        }
    return {
        "page_type": "daily_report",
        "date": nullable(daily_report.get("date", "")),
        "title": nullable(daily_report.get("title", "")),
        "season_window": nullable(infer_season_window(daily_report.get("date", ""))),
        "last_updated": generated_at.isoformat(timespec="seconds"),
        "summary": nullable(daily_report.get("summary", "")),
        "source_path": daily_report.get("source_path"),
        "mystic_focus": build_mystic_focus(daily_report),
        "psychology_analysis": build_psychology_analysis(daily_report),
        "cbt_event_analysis": build_cbt_event_analysis(daily_report),
        "physics_mirror": build_physics_mirror(daily_report),
        "daily_actions": build_daily_actions(daily_report),
        "term_heatmap": build_term_heatmap(daily_reports, ten_day_reports, monthly_summaries, growth_report),
    }


def parse_ascii_bar_section(block: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in block.splitlines():
        line = raw.rstrip()
        match = re.match(r"^\s*(\d+/\d+)\s+([█░]+)\s+(.+)$", line)
        if not match:
            continue
        date_label = match.group(1)
        bar = match.group(2)
        remainder = clean_inline(match.group(3))
        items.append(
            {
                "date": date_label.replace("/", "."),
                "value": bar.count("█"),
                "note": remainder,
                "highlight": "转折" in remainder or "爆发" in remainder or bar.count("█") <= 3 or bar.count("█") >= 8,
            }
        )
    return items


def build_phase_segments(ten_day_report: dict[str, Any]) -> list[dict[str, Any]]:
    block = ten_day_report.get("energy_block", "")
    pattern = re.compile(r"^\*\*第(.+?)阶段（(.+?)）[:：](.+?)\*\*\s*\n(.*?)(?=^\*\*第.+?阶段|\Z)", re.M | re.S)
    items: list[dict[str, Any]] = []
    for index, match in enumerate(pattern.finditer(block), start=1):
        items.append(
            {
                "title": clean_inline(match.group(3)),
                "range": clean_inline(match.group(2)).replace("-", " — "),
                "summary": sentence_excerpt(match.group(4), 90),
                "priority": index,
            }
        )
    return items


def build_capability_heatmap(ten_day_report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in ten_day_report.get("capability_change_table", []):
        name = clean_inline(row.get("能力维度", ""))
        if not name:
            continue
        start_score, end_score = TENDAY_CAPABILITY_SCORE_MAP.get(name, (4, 6))
        items.append(
            {
                "name": name,
                "start_score": start_score,
                "end_score": end_score,
                "delta": end_score - start_score,
                "summary": trim_text(clean_inline(row.get("3月15日的状态", "")), 60),
            }
        )
    return items


def build_physics_explanations(ten_day_report: dict[str, Any]) -> list[dict[str, Any]]:
    block = ten_day_report.get("physics_block", "")
    items: list[dict[str, Any]] = []
    pattern = re.compile(r"^\*\*(.+?)\*\*[:：]\s*(.+)$", re.M)
    for match in pattern.finditer(block):
        term = clean_inline(match.group(1))
        detail = excerpt_around_keyword(block, term, 110)
        items.append(
            {
                "term": term,
                "thesis": clean_inline(match.group(2)),
                "detail": detail,
            }
        )
    return items


def build_tracking_patterns(ten_day_report: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for title, body in ten_day_report.get("pattern_sections", []):
        pattern_name = clean_inline(title.split("：", 1)[-1]).strip('"')
        if not pattern_name:
            continue
        items.append(
            {
                "title": TENDAY_TRACKING_LIBRARY.get(pattern_name, "持续追踪"),
                "tracking_pattern": pattern_name,
                "note": trim_text(body, 90),
            }
        )
    return items


def build_tenday_report_page(generated_at: datetime, ten_day_report: dict[str, Any] | None) -> dict[str, Any]:
    if not ten_day_report:
        return {
            "page_type": "tenday_report",
            "title": None,
            "range": None,
            "last_updated": generated_at.isoformat(timespec="seconds"),
            "emotion_bars": [],
            "action_bars": [],
            "phase_segments": [],
            "capability_heatmap": [],
            "physics_explanations": [],
            "tracking_patterns": [],
        }
    range_value = None
    if ten_day_report.get("period_start") and ten_day_report.get("period_end"):
        range_value = f"{ten_day_report['period_start']}/{ten_day_report['period_end']}"
    return {
        "page_type": "tenday_report",
        "title": nullable(ten_day_report.get("title", "")),
        "range": range_value or nullable(ten_day_report.get("period_label", "")),
        "last_updated": generated_at.isoformat(timespec="seconds"),
        "summary": nullable(ten_day_report.get("summary", "")),
        "source_path": ten_day_report.get("source_path"),
        "emotion_bars": parse_ascii_bar_section(ten_day_report.get("emotion_block", "")),
        "action_bars": parse_ascii_bar_section(ten_day_report.get("action_block", "")),
        "phase_segments": build_phase_segments(ten_day_report),
        "capability_heatmap": build_capability_heatmap(ten_day_report),
        "physics_explanations": build_physics_explanations(ten_day_report),
        "tracking_patterns": build_tracking_patterns(ten_day_report),
    }


def build_panorama_cards(latest_month: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not latest_month:
        return []
    items: list[dict[str, Any]] = []
    for thread in latest_month.get("open_threads", []):
        metadata = MONTHLY_TOPIC_LIBRARY.get(thread.get("title", ""))
        if not metadata:
            continue
        items.append(
            {
                "id": metadata["id"],
                "domain": metadata["source_domain"],
                "priority": metadata["priority"],
                "objective": metadata["objective"],
                "action": metadata["action"],
                "tracking_pattern": metadata["tracking_pattern"],
            }
        )
    return items


def build_monthly_active_patterns(
    latest_month: dict[str, Any] | None,
    cognitive_state: dict[str, Any],
) -> list[dict[str, Any]]:
    if not latest_month:
        return []
    items: list[dict[str, Any]] = []
    for row in latest_month.get("active_patterns", []):
        raw_name = normalize_pattern_name(row.get("模式名称", ""))
        if not raw_name:
            continue
        pattern = cognitive_state["patterns"].get(slugify(raw_name), {})
        metadata = PATTERN_LIBRARY.get(raw_name, {})
        contract_status = contract_pattern_status(pattern.get("status", "active"))
        if contract_status == "rewriting":
            implication = f"{metadata.get('professional_name', raw_name)}已进入重写阶段，接下来要把“{metadata.get('rewrite_target', '新的反应方式')}”稳定下来。"
        elif contract_status == "active":
            implication = f"{metadata.get('professional_name', raw_name)}已经可以复现，当前要继续观察它在什么场景下最容易被触发。"
        else:
            implication = f"{metadata.get('professional_name', raw_name)}刚被看见，4月重点是继续积累证据，确认它的触发条件。"
        items.append(
            {
                "professional_name": metadata.get("professional_name", raw_name),
                "status": clean_inline(row.get("状态", "")),
                "implication": implication,
            }
        )
    return items


def build_open_topics(latest_month: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not latest_month:
        return []
    items: list[dict[str, Any]] = []
    for thread in latest_month.get("open_threads", []):
        metadata = MONTHLY_TOPIC_LIBRARY.get(thread.get("title", ""))
        if not metadata:
            continue
        items.append(
            {
                "source_domain": metadata["source_domain"],
                "topic_title": metadata["topic_title"],
                "note": thread.get("summary", ""),
            }
        )
    return items


def build_monthly_report_page(
    generated_at: datetime,
    latest_month: dict[str, Any] | None,
    cognitive_state: dict[str, Any],
) -> dict[str, Any]:
    month_value = None
    if latest_month and latest_month.get("date"):
        month_value = latest_month["date"][:7]
    return {
        "page_type": "monthly_report",
        "month": month_value,
        "title": nullable(latest_month.get("title", "")) if latest_month else None,
        "last_updated": generated_at.isoformat(timespec="seconds"),
        "summary": nullable(latest_month.get("summary", "")) if latest_month else None,
        "source_path": latest_month.get("source_path") if latest_month else None,
        "panorama_cards": build_panorama_cards(latest_month),
        "active_patterns": build_monthly_active_patterns(latest_month, cognitive_state),
        "open_topics": build_open_topics(latest_month),
    }

def write_state_files(
    config: ResolvedConfig,
    cognitive_state: dict[str, Any],
    report_index: dict[str, Any],
    reminders: dict[str, Any],
    suggestion_index: dict[str, Any],
) -> dict[str, str]:
    cognitive_state_path = config.paths["system_state"] / "cognitive_state.json"
    report_index_path = config.paths["indexes"] / "report_index.json"
    reminders_path = config.paths["reminders"]
    suggestion_index_path = config.paths["suggestion_index"]
    write_json(cognitive_state_path, cognitive_state)
    write_json(report_index_path, report_index)
    write_json(reminders_path, reminders)
    write_json(suggestion_index_path, suggestion_index)
    return {
        "cognitive_state": str(cognitive_state_path),
        "report_index": str(report_index_path),
        "reminders": str(reminders_path),
        "suggestion_index": str(suggestion_index_path),
    }


def build_payload(profile_override: str | None = None) -> dict[str, Any]:
    generated_at = now_local()
    config = load_config(profile_override)
    require_path(config.vault_root, "vault_root", expect_dir=True)
    daily_reports = sort_reports(
        [parse_daily_report(path) for path in collect_markdown_files(config.paths["daily_reports"], "daily_reports")]
    )
    ten_day_reports = sort_reports(
        [parse_ten_day_report(path) for path in collect_markdown_files(config.paths["ten_day_reports"], "ten_day_reports")]
    )
    monthly_summaries = sort_reports(
        [parse_monthly_summary(path) for path in collect_markdown_files(config.paths["monthly_reports"], "monthly_reports")]
    )
    growth_report = None
    if config.paths["growth_report"].exists():
        require_path(config.paths["growth_report"], "growth_report", expect_dir=False)
        growth_report = parse_growth_report(config.paths["growth_report"])

    cognitive_state, warnings = build_cognitive_state(
        daily_reports=daily_reports,
        ten_day_reports=ten_day_reports,
        monthly_summaries=monthly_summaries,
        growth_report=growth_report,
        config=config,
    )
    report_index = build_report_index(daily_reports, ten_day_reports, monthly_summaries, growth_report)
    suggestion_candidates = collect_suggestion_candidates(daily_reports, ten_day_reports, monthly_summaries)
    suggestion_index = build_suggestion_index(suggestion_candidates)
    reminders = build_reminders(suggestion_index, config, generated_at)
    suggestion_index = attach_suggestion_statuses(suggestion_index, reminders)
    artifact_paths = write_state_files(config, cognitive_state, report_index, reminders, suggestion_index)

    latest_daily = daily_reports[-1] if daily_reports else None
    latest_ten_day = ten_day_reports[-1] if ten_day_reports else None
    latest_month = monthly_summaries[-1] if monthly_summaries else None
    payload = {
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "profile": config.profile,
        "vault_root": str(config.vault_root),
        "artifact_paths": artifact_paths,
        "warnings": warnings,
        "pages": {
            "home": build_home_page(
                generated_at,
                cognitive_state,
                latest_month,
                growth_report,
                latest_daily,
                latest_ten_day,
                reminders,
            ),
            "daily_report": build_daily_report_page(
                generated_at,
                latest_daily,
                daily_reports,
                ten_day_reports,
                monthly_summaries,
                growth_report,
            ),
            "tenday_report": build_tenday_report_page(generated_at, latest_ten_day),
            "monthly_report": build_monthly_report_page(generated_at, latest_month, cognitive_state),
        },
        "state": cognitive_state,
        "report_index": report_index,
        "reminders": reminders,
        "suggestion_index": suggestion_index,
    }
    return payload


def write_workspace_outputs(payload: dict[str, Any]) -> None:
    JSON_OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    js_payload = "window.COGNITIVE_WORKBENCH_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    JS_OUTPUT.write_text(js_payload, encoding="utf-8")
    PREVIEW_PUBLIC_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_PUBLIC_OUTPUT.write_text(js_payload, encoding="utf-8")
    PREVIEW_DIST_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIST_OUTPUT.write_text(js_payload, encoding="utf-8")


def print_summary(payload: dict[str, Any], wrote_workspace_output: bool) -> None:
    print(f"Profile: {payload['profile']}")
    print(f"Vault root: {payload['vault_root']}")
    home = payload["pages"]["home"]
    report_types = Counter(item["type"] for item in payload["report_index"]["items"])
    print(
        "Reports: "
        f"daily={report_types['daily']} "
        f"ten_day={report_types['ten_day']} "
        f"monthly={report_types['monthly']} "
        f"growth={report_types['growth']}"
    )
    print(
        "Pages: "
        f"patterns={len(home['patterns'])} "
        f"beliefs={len(home['belief_migrations'])} "
        f"capabilities={len(home['capabilities'])} "
        f"mechanisms={len(home['verified_mechanisms'])}"
    )
    print(
        "Reminders: "
        f"items={len(payload['reminders']['items'])} "
        f"suggestions={len(payload['suggestion_index']['items'])} "
        f"home_active={len(home.get('active_reminders', []))}"
    )
    if wrote_workspace_output:
        print(f"Wrote {JSON_OUTPUT}")
        print(f"Wrote {JS_OUTPUT}")
        print(f"Wrote {PREVIEW_PUBLIC_OUTPUT}")
        print(f"Wrote {PREVIEW_DIST_OUTPUT}")
    print(f"Wrote {payload['artifact_paths']['cognitive_state']}")
    print(f"Wrote {payload['artifact_paths']['report_index']}")
    print(f"Wrote {payload['artifact_paths']['reminders']}")
    print(f"Wrote {payload['artifact_paths']['suggestion_index']}")
    if payload["warnings"]:
        print("Warnings:")
        for warning in payload["warnings"]:
            print(f"- {warning}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate cognitive workbench data from the configured vault.")
    parser.add_argument(
        "--profile",
        choices=get_available_profiles(),
        help="Config profile to use. Defaults to COGNITIVE_PROFILE or the config default.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the generated payload JSON to stdout after writing files.",
    )
    parser.add_argument(
        "--no-workbench-output",
        action="store_true",
        help="Skip writing workspace-level cognitive-workbench-data.{json,js} files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_payload(args.profile)
    wrote_workspace_output = not args.no_workbench_output
    if wrote_workspace_output:
        write_workspace_outputs(payload)
    print_summary(payload, wrote_workspace_output)
    if args.stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
