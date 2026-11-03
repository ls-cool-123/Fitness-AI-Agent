"""把用户/LLM 的口语输入归一成计划生成器可用的枚举。

LLM 可能把 ``experience`` 传成 "新手"，把 ``split`` 传成 "三分化"，把
``day_focus`` 传成 "胸、肩、三头" 或 "推/拉/腿"。这一层只做纯字符串映射，
不做数据库/LLM 调用，方便单测。
"""

from __future__ import annotations

import re
from typing import Literal

from agent.plans.catalog import MUSCLE_GROUP_NAMES, MUSCLE_GROUPS

Experience = Literal["beginner", "experienced"]
Split = Literal["three_day", "five_day"]

_EXPERIENCE_ALIASES: dict[str, Experience] = {
    "beginner": "beginner",
    "新手": "beginner",
    "无经验": "beginner",
    "没有经验": "beginner",
    "没有训练经验": "beginner",
    "无训练经验": "beginner",
    "没经验": "beginner",
    "零基础": "beginner",
    "a": "beginner",
    "选a": "beginner",
    "选择a": "beginner",
    "选项a": "beginner",
    "第一个": "beginner",
    "第一种": "beginner",
    "无": "beginner",
    "没有": "beginner",
    "0": "beginner",
    "1": "beginner",
    "experienced": "experienced",
    "老手": "experienced",
    "进阶": "experienced",
    "有经验": "experienced",
    "有训练经验": "experienced",
    "练过": "experienced",
    "b": "experienced",
    "选b": "experienced",
    "选择b": "experienced",
    "选项b": "experienced",
    "第二个": "experienced",
    "第二种": "experienced",
    "有": "experienced",
    "2": "experienced",
}

_SPLIT_ALIASES: dict[str, Split] = {
    "three_day": "three_day",
    "three": "three_day",
    "3": "three_day",
    "1": "three_day",
    "三分化": "three_day",
    "3分化": "three_day",
    "三分": "three_day",
    "三": "three_day",
    "a": "three_day",
    "选a": "three_day",
    "选择a": "three_day",
    "选项a": "three_day",
    "第一个": "three_day",
    "五种": "five_day",
    "five_day": "five_day",
    "five": "five_day",
    "5": "five_day",
    "2": "five_day",
    "五分化": "five_day",
    "5分化": "five_day",
    "五分": "five_day",
    "五": "five_day",
    "b": "five_day",
    "选b": "five_day",
    "选择b": "five_day",
    "选项b": "five_day",
    "第二个": "five_day",
}

_GOAL_ALIASES: dict[str, str] = {
    "增肌": "增肌",
    "增肌减脂": "增肌",
    "hypertrophy": "增肌",
    "肌肉": "增肌",
    "力量": "力量",
    "strength": "力量",
    "提升力量": "力量",
    "减脂": "减脂",
    "fat loss": "减脂",
    "cut": "减脂",
    "瘦": "减脂",
    "塑形": "塑形",
    "线条": "塑形",
    "toning": "塑形",
}

# 肌群中文名 / 英文 id / 常见口语别名 -> 标准中文肌群名
_MUSCLE_ALIASES: dict[str, str] = {
    "chest": "胸",
    "胸": "胸",
    "胸肌": "胸",
    "胸部": "胸",
    "back": "背",
    "背": "背",
    "背肌": "背",
    "背部": "背",
    "shoulders": "肩",
    "肩": "肩",
    "肩肌": "肩",
    "肩部": "肩",
    "肩膀": "肩",
    "biceps": "二头",
    "二头": "二头",
    "二头肌": "二头",
    "肱二头肌": "二头",
    "triceps": "三头",
    "三头": "三头",
    "三头肌": "三头",
    "肱三头肌": "三头",
    "quads": "股四头",
    "股四头": "股四头",
    "股四头肌": "股四头",
    "大腿": "股四头",
    "大腿前侧": "股四头",
    "glutes": "臀",
    "臀": "臀",
    "臀部": "臀",
    "臀肌": "臀",
    "hamstrings": "腘绳肌",
    "腘绳肌": "腘绳肌",
    "腿后侧": "腘绳肌",
    "大腿后侧": "腘绳肌",
    "calves": "小腿",
    "小腿": "小腿",
    "腓肠肌": "小腿",
    "core": "核心",
    "核心": "核心",
    "腹": "核心",
    "腹肌": "核心",
    "腹部": "核心",
}

# 复合简称展开
_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "推": ("胸", "肩", "三头"),
    "push": ("胸", "肩", "三头"),
    "拉": ("背", "二头"),
    "pull": ("背", "二头"),
    "腿": ("股四头", "臀", "腘绳肌", "小腿", "核心"),
    "legs": ("股四头", "臀", "腘绳肌", "小腿", "核心"),
    "下肢": ("股四头", "臀", "腘绳肌", "小腿", "核心"),
    "手臂": ("二头", "三头"),
    "arms": ("二头", "三头"),
    "上肢": ("胸", "背", "肩", "二头", "三头"),
    "upper": ("胸", "背", "肩", "二头", "三头"),
    "全身": tuple(group.name for group in MUSCLE_GROUPS),
    "full body": tuple(group.name for group in MUSCLE_GROUPS),
    "full": tuple(group.name for group in MUSCLE_GROUPS),
}

_SPLIT_RE = re.compile(r"[,，、/|;；]+")
_SPACE_RE = re.compile(r"\s+")


def _clean(value: object) -> str:
    """把任意输入转成去掉首尾空白的小写字符串。"""
    if value is None:
        return ""
    return str(value).strip().lower()


def _match_alias(value: object, aliases: dict[str, object]) -> object | None:
    """先精确匹配，再按「较长的别名包含在输入里」匹配。

    后者用于处理"我是新手""选A""没有训练经验"这类自由回答；按长度倒序，
    保证"没有训练经验"不会被较短的"有训练经验"抢先匹配。
    """
    text = _clean(value).strip(" .。、,，:：;；()（）")
    if not text:
        return None
    compact = text.replace(" ", "")
    if compact in aliases:
        return aliases[compact]
    for key, result in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if len(key) >= 2 and key in compact:
            return result
    return None


def normalize_experience(value: object) -> Experience | None:
    """把经验输入归一成 beginner/experienced，无法识别返回 None。

    额外支持选项字母：A=新手、B=老手；1=新手、2=老手。
    """
    result = _match_alias(value, _EXPERIENCE_ALIASES)
    return result if result in ("beginner", "experienced") else None  # type: ignore[return-value]


def normalize_split(value: object) -> Split | None:
    """把分化输入归一成 three_day/five_day，无法识别返回 None。

    额外支持选项字母：A=三分化、B=五分化；1=三分化、2=五分化。
    """
    result = _match_alias(value, _SPLIT_ALIASES)
    return result if result in ("three_day", "five_day") else None  # type: ignore[return-value]


def normalize_goal(value: object) -> str:
    """把目标归一成增肌/力量/减脂/塑形，默认增肌。"""
    return _GOAL_ALIASES.get(_clean(value), "增肌")


def normalize_muscle(value: object) -> str | None:
    """把单个肌群输入归一成标准中文名，无法识别返回 None。"""
    return _MUSCLE_ALIASES.get(_clean(value))


def _split_tokens(value: object) -> list[str]:
    """把字符串/列表拆成 token，保留 "full body" 这类空格短语。"""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_items: list[object] = []
        for item in value:
            if isinstance(item, (list, tuple, set)):
                raw_items.extend(item)
            else:
                raw_items.append(item)
    else:
        raw_items = [value]

    tokens: list[str] = []
    for item in raw_items:
        text = _clean(item)
        if not text:
            continue
        # 先按标点拆；没有标点时保留空格短语（如 full body），
        # 其余普通空格再拆成多块。
        for part in _SPLIT_RE.split(text):
            part = part.strip()
            if not part:
                continue
            if part in _EXPANSIONS:
                tokens.append(part)
                continue
            tokens.extend(piece for piece in _SPACE_RE.split(part) if piece)
    return tokens


def expand_focus_token(value: object) -> list[str]:
    """展开单个部位 token；未知 token 返回空列表。"""
    text = _clean(value)
    if not text:
        return []
    if text in _EXPANSIONS:
        return list(_EXPANSIONS[text])
    muscle = normalize_muscle(text)
    return [muscle] if muscle else []


def normalize_muscle_list(value: object) -> list[str]:
    """把 "胸、肩、三头" / ["胸","肩"] / "推" 展开成去重的标准肌群列表。"""
    result: list[str] = []
    for token in _split_tokens(value):
        for muscle in expand_focus_token(token):
            if muscle in MUSCLE_GROUP_NAMES and muscle not in result:
                result.append(muscle)
    return result


def normalize_avoid(value: object) -> list[str]:
    """把要避开的动作/关键词归一成去重列表，最多 20 个。"""
    result: list[str] = []
    for token in _split_tokens(value):
        if token and token not in result:
            result.append(token)
    return result[:20]


def normalize_plan_name(value: object) -> str | None:
    """清理用户自定义计划名，空值返回 None。"""
    text = str(value).strip() if value is not None else ""
    return text[:100] or None


def parse_day_focus(value: object, split: Split) -> tuple[list[list[str]] | None, str | None]:
    """解析用户指定的每日部位。

    Returns:
        ``(day_focus, error)``。``day_focus is None`` 表示使用默认分化模板；
        ``error`` 非空时调用方应把错误交回 Agent 继续追问。
    """
    expected_days = 3 if split == "three_day" else 5
    if value is None:
        return None, None

    items: list[object]
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        items = [value]

    if not items:
        return None, None

    # 允许 LLM 传成 [[...], [...]]，也允许一维的 ["胸、肩", "背、二头", ...]
    days: list[list[str]] = []
    for item in items:
        if isinstance(item, (list, tuple, set)):
            days.append(normalize_muscle_list(list(item)))
        else:
            text = str(item).strip()
            if not text:
                days.append([])
                continue
            # 单个字符串里用分号/换行分隔多天时也支持
            parts = [part for part in re.split(r"[;；\n]+", text) if part.strip()]
            if len(parts) > 1:
                days.extend(normalize_muscle_list(part) for part in parts)
            else:
                days.append(normalize_muscle_list(text))

    if len(days) != expected_days:
        return None, f"{expected_days} 分化需要恰好 {expected_days} 个训练日，你给了 {len(days)} 个。请按天告诉我每个训练日练哪些部位。"
    if any(not day for day in days):
        return None, "有训练日没有识别出有效部位。可用部位：" + "、".join(group.name for group in MUSCLE_GROUPS) + "。"
    return days, None
