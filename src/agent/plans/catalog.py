"""静态训练动作库与肌群定义。

动作数据不落 MySQL 的独立表：它是计划生成器的输入，需要可测试、可版本化，
而且和 ExerciseCatalog 的「训练记录匹配」职责不同。训练记录仍然通过
``exercise_catalog`` 表匹配动作名；这里只负责「计划推荐」。

每个动作只有一个主肌群。跨肌群动作（如双杠臂屈伸）按主要训练目的归类，
避免同一动作在计划里出现两次。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Level = Literal["beginner", "experienced", "all"]


@dataclass(frozen=True, slots=True)
class MuscleGroupSpec:
    """一个训练肌群的展示信息。

    ``id`` 是前端 3D 模型匹配用的稳定英文键；``name`` 是中文展示名，也是
    ``ExerciseSpec.muscle_group`` 的取值。
    """

    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ExerciseSpec:
    """一个可被计划推荐的训练动作。"""

    name: str
    category: str
    muscle_group: str
    level: Level
    equipment: str
    is_compound: bool
    default_sets: int
    default_reps: str
    rest_seconds: int
    description: str
    aliases: tuple[str, ...] = ()


MUSCLE_GROUPS: tuple[MuscleGroupSpec, ...] = (
    MuscleGroupSpec("chest", "胸", "胸大肌/胸小肌，负责水平推与夹胸。"),
    MuscleGroupSpec("back", "背", "背阔肌、斜方肌、菱形肌与竖脊肌，负责拉与躯干稳定。"),
    MuscleGroupSpec("shoulders", "肩", "三角肌前中后束与肩袖，负责推举、侧平举和后束训练。"),
    MuscleGroupSpec("biceps", "二头", "肱二头肌与肱肌，负责屈肘和旋后。"),
    MuscleGroupSpec("triceps", "三头", "肱三头肌，负责伸肘，是推类动作的协同主力。"),
    MuscleGroupSpec("quads", "股四头", "股四头肌，负责伸膝，深蹲/腿举的主发力肌。"),
    MuscleGroupSpec("glutes", "臀", "臀大肌/臀中肌/臀小肌，负责伸髋与髋外展。"),
    MuscleGroupSpec("hamstrings", "腘绳肌", "股二头肌、半腱肌、半膜肌，负责屈膝与伸髋。"),
    MuscleGroupSpec("calves", "小腿", "腓肠肌与比目鱼肌，负责踝跖屈。"),
    MuscleGroupSpec("core", "核心", "腹直肌、腹内外斜肌与腹横肌，负责躯干稳定与屈曲。"),
)

MUSCLE_GROUP_NAMES: frozenset[str] = frozenset(group.name for group in MUSCLE_GROUPS)
MUSCLE_GROUP_BY_NAME: dict[str, MuscleGroupSpec] = {group.name: group for group in MUSCLE_GROUPS}
MUSCLE_GROUP_BY_ID: dict[str, MuscleGroupSpec] = {group.id: group for group in MUSCLE_GROUPS}


# (name, category, muscle_group, level, equipment, is_compound, sets, reps, rest, description, aliases)
_RAW_EXERCISES: tuple[tuple[str, str, str, Level, str, bool, int, str, int, str, tuple[str, ...]], ...] = (
    # ── 胸 ──
    ("卧推", "胸", "胸", "experienced", "杠铃", True, 4, "6-10", 120, "肩胛后缩下沉，杠铃下放到胸骨中下部。", ("bench press", "barbell bench press", "杠铃卧推")),
    ("哑铃卧推", "胸", "胸", "beginner", "哑铃", True, 3, "8-12", 90, "哑铃下放到胸两侧，肘部约 45 度。", ("dumbbell bench press", "db bench press")),
    ("上斜卧推", "胸", "胸", "experienced", "杠铃", True, 4, "6-10", 120, "上斜 30–45 度，主练上胸。", ("incline bench press", "incline barbell bench")),
    ("上斜哑铃卧推", "胸", "胸", "experienced", "哑铃", True, 4, "8-12", 90, "上斜凳 + 哑铃，活动范围更大。", ("incline dumbbell bench press", "incline db bench")),
    ("下斜卧推", "胸", "胸", "experienced", "杠铃", True, 4, "8-12", 90, "下斜角度不宜过大，注意肩部舒适度。", ("decline bench press",)),
    ("飞鸟", "胸", "胸", "beginner", "哑铃", False, 3, "12-15", 60, "肘部微屈固定，用胸肌把哑铃合拢。", ("fly", "dumbbell fly", "chest fly", "哑铃飞鸟")),
    ("绳索夹胸", "胸", "胸", "experienced", "绳索", False, 3, "12-15", 60, "身体前倾，顶峰收缩时双手交叉。", ("cable crossover", "cable fly", "龙门架夹胸")),
    ("俯卧撑", "胸", "胸", "beginner", "自重", True, 3, "10-15", 60, "核心收紧，身体成一条直线，胸口接近地面。", ("push up", "pushup", "push-ups")),
    ("器械推胸", "胸", "胸", "beginner", "器械", True, 3, "8-12", 90, "固定轨迹，适合新手建立推的发力感。", ("chest press machine", "坐姿推胸")),

    # ── 背 ──
    ("引体向上", "背", "背", "experienced", "自重", True, 4, "6-10", 120, "先沉肩再拉，胸口找单杠。", ("pull up", "pullup", "chin up", "chinup")),
    ("杠铃划船", "背", "背", "experienced", "杠铃", True, 4, "8-12", 120, "髋铰链俯身，杠铃拉向腹部，避免耸肩。", ("barbell row", "划船")),
    ("哑铃划船", "背", "背", "beginner", "哑铃", True, 3, "10-12", 90, "单臂支撑，肘部贴身体向后拉。", ("dumbbell row", "db row", "单臂哑铃划船")),
    ("高位下拉", "背", "背", "beginner", "绳索", True, 3, "10-12", 90, "胸口上挺，拉杆到锁骨附近。", ("lat pulldown", "pull down", "lat pull down")),
    ("坐姿划船", "背", "背", "beginner", "绳索", True, 3, "10-12", 90, "保持躯干稳定，肩胛后缩再拉。", ("seated row", "seated cable row", "绳索划船")),
    ("T杠划船", "背", "背", "experienced", "杠铃", True, 4, "8-12", 120, "胸口垫稳，肘部向后拉，减少腰部代偿。", ("t-bar row", "t bar row")),
    ("直臂下压", "背", "背", "beginner", "绳索", False, 3, "12-15", 60, "手臂伸直下压，感受背阔肌拉伸与收缩。", ("straight arm pulldown", "直臂下拉")),
    ("硬拉", "背", "背", "experienced", "杠铃", True, 4, "4-6", 180, "杠铃贴腿，背部中立，伸髋站直。", ("deadlift", "传统硬拉", "杠铃硬拉", "conventional deadlift")),
    ("架上硬拉", "背", "背", "experienced", "杠铃", True, 4, "6-8", 150, "从膝上启动，强化上背与锁定。", ("rack pull",)),
    ("对握引体", "背", "背", "experienced", "自重", True, 4, "6-10", 120, "对握更偏背阔肌与肱肌，肩部更友好。", ("neutral grip pull up",)),

    # ── 肩 ──
    ("推举", "肩", "肩", "experienced", "杠铃", True, 4, "6-10", 120, "核心收紧，杠铃过头时头部稍前移。", ("overhead press", "shoulder press", "杠铃推举", "ohp")),
    ("哑铃推举", "肩", "肩", "beginner", "哑铃", True, 3, "8-12", 90, "坐姿或站姿，哑铃沿耳侧上推。", ("dumbbell press", "dumbbell shoulder press", "db press")),
    ("侧平举", "肩", "肩", "beginner", "哑铃", False, 3, "12-15", 60, "肘部微屈，抬到肩高即可，避免借力。", ("lateral raise", "哑铃侧平举")),
    ("前平举", "肩", "肩", "beginner", "哑铃", False, 3, "12-15", 60, "小重量控制，抬到眼高。", ("front raise", "哑铃前平举")),
    ("俯身飞鸟", "肩", "肩", "beginner", "哑铃", False, 3, "12-15", 60, "俯身，肘部微屈，向后束方向打开。", ("rear delt fly", "反向飞鸟", "reverse fly")),
    ("面拉", "肩", "肩", "experienced", "绳索", False, 3, "12-15", 60, "绳索拉向面部，外旋肩关节。", ("face pull",)),
    ("阿诺德推举", "肩", "肩", "experienced", "哑铃", True, 4, "8-12", 90, "从掌心向内旋转到向上推，活动范围更大。", ("arnold press",)),
    ("直立划船", "肩", "肩", "experienced", "杠铃", False, 3, "10-12", 90, "肘部领先，不要拉到下巴以上。", ("upright row",)),
    ("杠铃耸肩", "肩", "肩", "beginner", "杠铃", False, 3, "12-15", 60, "只做耸肩，不要转动肩关节。", ("shrug", "barbell shrug")),

    # ── 二头 ──
    (
        "二头弯举",
        "手臂",
        "二头",
        "beginner",
        "哑铃",
        False,
        3,
        "10-12",
        60,
        "肘部固定在体侧，避免身体摆动。",
        ("bicep curl", "curl", "哑铃弯举", "杠铃弯举", "barbell curl"),
    ),
    ("锤式弯举", "手臂", "二头", "beginner", "哑铃", False, 3, "10-12", 60, "掌心相对，兼顾肱肌与肱桡肌。", ("hammer curl",)),
    ("集中弯举", "手臂", "二头", "experienced", "哑铃", False, 3, "10-12", 60, "肘部抵住大腿内侧，顶峰收缩。", ("concentration curl",)),
    ("牧师凳弯举", "手臂", "二头", "experienced", "杠铃", False, 3, "8-12", 75, "上臂贴住斜板，下放到底但不要锁死肘。", ("preacher curl",)),

    # ── 三头 ──
    ("三头下压", "手臂", "三头", "beginner", "绳索", False, 3, "12-15", 60, "肘部固定，前臂下压到伸直。", ("tricep pushdown", "cable pushdown")),
    ("绳索下压", "手臂", "三头", "beginner", "绳索", False, 3, "12-15", 60, "用绳索在底部外旋分开，增强收缩。", ("rope pushdown", "tricep rope")),
    ("窄距卧推", "手臂", "三头", "experienced", "杠铃", True, 4, "6-10", 120, "握距略窄于肩，肘部贴近身体。", ("close grip bench press", "窄握卧推")),
    ("法式弯举", "手臂", "三头", "experienced", "哑铃", False, 3, "10-12", 75, "肘部朝上，下放到头后拉伸三头。", ("skull crusher", "仰卧臂屈伸")),
    ("双杠臂屈伸", "手臂", "三头", "experienced", "自重", True, 4, "8-12", 120, "身体直立偏三头，前倾偏胸；肩不适则换下压。", ("dip", "dips", "臂屈伸")),

    # ── 股四头 ──
    ("深蹲", "腿", "股四头", "experienced", "杠铃", True, 4, "5-8", 180, "膝盖对齐脚尖，蹲到大腿接近平行。", ("squat", "杠铃深蹲", "barbell squat", "back squat")),
    ("前蹲", "腿", "股四头", "experienced", "杠铃", True, 4, "5-8", 180, "杠铃置于前三角，躯干更直立，主练股四头。", ("front squat",)),
    ("腿举", "腿", "股四头", "beginner", "器械", True, 3, "10-12", 90, "脚掌踩稳，下放到膝盖约 90 度。", ("leg press", "倒蹬")),
    ("哈克深蹲", "腿", "股四头", "experienced", "器械", True, 4, "8-12", 120, "背部贴紧靠垫，膝盖对齐脚尖。", ("hack squat",)),
    ("腿屈伸", "腿", "股四头", "beginner", "器械", False, 3, "12-15", 60, "顶峰伸直但不要猛锁膝。", ("leg extension",)),
    ("弓步", "腿", "股四头", "beginner", "哑铃", True, 3, "10-12", 90, "前后脚都稳，前膝对齐脚尖。", ("lunge", "箭步蹲", "弓步蹲", "walking lunge")),
    ("保加利亚分腿蹲", "腿", "股四头", "experienced", "哑铃", True, 4, "8-12", 90, "后脚垫高，重心放在前腿。", ("bulgarian split squat", "保加利亚蹲")),
    ("高脚杯深蹲", "腿", "股四头", "beginner", "哑铃", True, 3, "10-12", 90, "哑铃抱在胸前，适合学习深蹲模式。", ("goblet squat",)),

    # ── 臀 ──
    ("臀推", "腿", "臀", "experienced", "杠铃", True, 4, "8-12", 90, "肩胛抵凳，顶峰夹臀，不要用腰代偿。", ("hip thrust", "杠铃臀推")),
    ("臀桥", "腿", "臀", "beginner", "自重", True, 3, "12-15", 60, "仰卧屈膝，脚跟发力把髋顶起。", ("glute bridge", "桥式")),
    ("髋外展", "腿", "臀", "beginner", "器械", False, 3, "12-15", 60, "坐姿或站姿外展，感受臀中肌。", ("hip abduction", "abductor machine")),
    ("相扑硬拉", "腿", "臀", "experienced", "杠铃", True, 4, "5-8", 180, "宽站距，膝盖外展，髋部发力站直。", ("sumo deadlift",)),
    ("绳索后踢", "腿", "臀", "experienced", "绳索", False, 3, "12-15", 60, "髋部稳定，腿向后伸，顶峰夹臀。", ("cable kickback", "glute kickback")),
    ("侧向弓步", "腿", "臀", "beginner", "哑铃", True, 3, "10-12", 75, "向侧方跨步，屈髋屈膝，主练臀中肌。", ("lateral lunge", "side lunge")),

    # ── 腘绳肌 ──
    ("腿弯举", "腿", "腘绳肌", "beginner", "器械", False, 3, "10-15", 60, "固定大腿，脚跟向臀部方向弯举。", ("leg curl", "俯卧腿弯举")),
    ("罗马尼亚硬拉", "腿", "腘绳肌", "experienced", "杠铃", True, 4, "6-10", 150, "髋向后推，杠铃贴腿，感受腿后侧拉伸。", ("romanian deadlift", "rdl", "直腿硬拉")),
    ("早安式", "腿", "腘绳肌", "experienced", "杠铃", True, 4, "6-10", 120, "杠铃置于上背，屈髋俯身，背部中立。", ("good morning",)),
    (
        "单腿罗马尼亚硬拉",
        "腿",
        "腘绳肌",
        "experienced",
        "哑铃",
        True,
        3,
        "8-12",
        90,
        "单腿支撑，髋部保持水平，兼顾平衡。",
        ("single leg rdl", "single-leg romanian deadlift"),
    ),
    ("坐姿腿弯举", "腿", "腘绳肌", "beginner", "器械", False, 3, "10-15", 60, "坐姿固定大腿，向臀部方向弯举。", ("seated leg curl",)),

    # ── 小腿 ──
    ("站姿提踵", "腿", "小腿", "beginner", "器械", False, 3, "12-20", 60, "前脚掌踩稳，脚跟尽量下沉再提起。", ("standing calf raise",)),
    ("坐姿提踵", "腿", "小腿", "beginner", "器械", False, 3, "12-20", 60, "坐姿屈膝，主练比目鱼肌。", ("seated calf raise",)),
    ("单腿提踵", "腿", "小腿", "experienced", "自重", False, 3, "12-15", 60, "单腿完成，控制下放，避免弹震。", ("single leg calf raise",)),
    ("负重提踵", "腿", "小腿", "experienced", "哑铃", False, 4, "10-15", 75, "手持哑铃增加负荷，顶峰停顿。", ("weighted calf raise", "dumbbell calf raise")),

    # ── 核心 ──
    ("卷腹", "核心", "核心", "beginner", "自重", False, 3, "12-20", 45, "下背贴地，用腹肌把肩胛卷离地面。", ("crunch", "ab crunch")),
    ("平板支撑", "核心", "核心", "beginner", "自重", False, 3, "30-60 秒", 45, "肘在肩下，身体成直线，不要塌腰。", ("plank",)),
    ("仰卧起坐", "核心", "核心", "beginner", "自重", False, 3, "12-20", 45, "屈膝仰卧，起身时呼气，避免抱头拉颈。", ("sit up", "situp")),
    ("悬垂举腿", "核心", "核心", "experienced", "自重", False, 3, "8-15", 60, "悬垂稳定，骨盆后倾，把腿抬向胸口。", ("hanging leg raise",)),
    ("俄罗斯转体", "核心", "核心", "experienced", "自重", False, 3, "15-20", 45, "躯干转动带动双手，不要只摆手臂。", ("russian twist",)),
    ("两头起", "核心", "核心", "experienced", "自重", False, 3, "10-15", 60, "手脚同时离地，顶峰折叠，控制下放。", ("v-up", "v up")),

    # ── 有氧（不参与力量分化，保留给训练记录匹配） ──
    ("跑步", "有氧", "有氧", "all", "自重", False, 1, "20-40 分钟", 0, "保持能对话的强度，注意落地缓冲。", ("run", "running", "jogging", "慢跑", "treadmill", "跑步机")),
    ("跳绳", "有氧", "有氧", "all", "自重", False, 1, "10-20 分钟", 0, "前脚掌落地，手腕发力摇绳。", ("jump rope", "skipping")),
    ("骑行", "有氧", "有氧", "all", "器械", False, 1, "30-60 分钟", 0, "调整座高，保持踏频与膝盖方向。", ("cycling", "bike", "biking", "动感单车", "spinning")),
    ("椭圆机", "有氧", "有氧", "all", "器械", False, 1, "20-40 分钟", 0, "低冲击有氧，注意脚掌不要离踏板。", ("elliptical", "elliptical machine")),
    ("划船机", "有氧", "有氧", "all", "器械", False, 1, "15-30 分钟", 0, "腿-髋-手臂的顺序发力，回程相反。", ("rowing machine", "rower", "rowing")),
    ("游泳", "有氧", "有氧", "all", "自重", False, 1, "20-40 分钟", 0, "全身低冲击有氧，注意呼吸节奏。", ("swim", "swimming")),
)

EXERCISES: tuple[ExerciseSpec, ...] = tuple(
    ExerciseSpec(
        name=name,
        category=category,
        muscle_group=muscle_group,
        level=level,
        equipment=equipment,
        is_compound=is_compound,
        default_sets=default_sets,
        default_reps=default_reps,
        rest_seconds=rest_seconds,
        description=description,
        aliases=aliases,
    )
    for (
        name,
        category,
        muscle_group,
        level,
        equipment,
        is_compound,
        default_sets,
        default_reps,
        rest_seconds,
        description,
        aliases,
    ) in _RAW_EXERCISES
)

EXERCISE_BY_NAME: dict[str, ExerciseSpec] = {exercise.name: exercise for exercise in EXERCISES}

# 名称/别名 → 动作。先放标准名，再放别名，保证重名时标准名优先。
EXERCISE_BY_ALIAS: dict[str, ExerciseSpec] = {}
for _exercise in EXERCISES:
    EXERCISE_BY_ALIAS.setdefault(_exercise.name.lower(), _exercise)
for _exercise in EXERCISES:
    for _alias in _exercise.aliases:
        EXERCISE_BY_ALIAS.setdefault(_alias.strip().lower(), _exercise)

_EQUIPMENT_PREFIXES = ("杠铃", "哑铃", "器械", "绳索", "史密斯")


def find_exercise(value: object) -> ExerciseSpec | None:
    """按标准名/别名/器械前缀解析动作。

    用户经常说"杠铃卧推"，而动作库标准名是"卧推"；"把哑铃卧推换成杠铃卧推"
    这类修改请求必须能解析到正确动作，否则工具会一直返回找不到动作。
    """
    text = str(value).strip() if value is not None else ""
    if not text:
        return None
    exact = EXERCISE_BY_NAME.get(text) or EXERCISE_BY_ALIAS.get(text.lower())
    if exact:
        return exact
    for prefix in _EQUIPMENT_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix) + 1:
            stripped = text[len(prefix) :].strip()
            match = EXERCISE_BY_NAME.get(stripped) or EXERCISE_BY_ALIAS.get(stripped.lower())
            if match:
                return match
    return None


# 动作模式：下拉框只推荐「同一种动作」，避免把推胸换成夹胸这类不同模式。
# 名字不在表里的动作归为「其他」，不会和正常模式混在一起。
_EXERCISE_PATTERNS: dict[str, str] = {
    # 胸
    "卧推": "推胸",
    "哑铃卧推": "推胸",
    "上斜卧推": "推胸",
    "上斜哑铃卧推": "推胸",
    "下斜卧推": "推胸",
    "器械推胸": "推胸",
    "俯卧撑": "推胸",
    "飞鸟": "夹胸",
    "绳索夹胸": "夹胸",
    # 背
    "引体向上": "下拉/引体",
    "高位下拉": "下拉/引体",
    "对握引体": "下拉/引体",
    "杠铃划船": "划船",
    "哑铃划船": "划船",
    "坐姿划船": "划船",
    "T杠划船": "划船",
    "硬拉": "硬拉",
    "架上硬拉": "硬拉",
    "直臂下压": "直臂下压",
    # 肩
    "推举": "推举",
    "哑铃推举": "推举",
    "阿诺德推举": "推举",
    "侧平举": "侧平举",
    "前平举": "前平举",
    "俯身飞鸟": "后束",
    "面拉": "后束",
    "直立划船": "直立划船",
    "杠铃耸肩": "耸肩",
    # 二头
    "二头弯举": "弯举",
    "锤式弯举": "弯举",
    "集中弯举": "弯举",
    "牧师凳弯举": "弯举",
    # 三头
    "三头下压": "下压",
    "绳索下压": "下压",
    "法式弯举": "臂屈伸",
    "双杠臂屈伸": "臂屈伸",
    "窄距卧推": "窄距推",
    # 股四头
    "深蹲": "深蹲",
    "前蹲": "深蹲",
    "高脚杯深蹲": "深蹲",
    "哈克深蹲": "深蹲",
    "腿举": "腿举",
    "弓步": "弓步",
    "保加利亚分腿蹲": "弓步",
    "腿屈伸": "腿屈伸",
    # 臀
    "臀推": "臀推/臀桥",
    "臀桥": "臀推/臀桥",
    "髋外展": "髋外展",
    "侧向弓步": "髋外展",
    "绳索后踢": "后踢",
    "相扑硬拉": "硬拉",
    # 腘绳肌
    "腿弯举": "腿弯举",
    "坐姿腿弯举": "腿弯举",
    "罗马尼亚硬拉": "髋铰链",
    "早安式": "髋铰链",
    "单腿罗马尼亚硬拉": "髋铰链",
    # 小腿
    "站姿提踵": "提踵",
    "坐姿提踵": "提踵",
    "单腿提踵": "提踵",
    "负重提踵": "提踵",
    # 核心
    "卷腹": "卷腹",
    "仰卧起坐": "卷腹",
    "两头起": "卷腹",
    "平板支撑": "平板",
    "悬垂举腿": "举腿",
    "俄罗斯转体": "转体",
}


def exercise_pattern(exercise: ExerciseSpec) -> str:
    """返回动作模式；用于下拉框只推荐同模式动作。"""
    return _EXERCISE_PATTERNS.get(exercise.name, "其他")


def level_allows(exercise_level: Level, requested: Level) -> bool:
    """判断某个动作是否适合目标水平。

    - 新手计划只能选 beginner/all；
    - 有经验计划可以选所有动作（老手也会用基础动作）。
    """
    if requested == "beginner":
        return exercise_level in ("beginner", "all")
    return exercise_level in ("beginner", "experienced", "all")


def exercises_for_group(muscle_group: str, requested_level: Level) -> list[ExerciseSpec]:
    """按肌群和目标水平筛选动作，保持动作库里的稳定顺序。"""
    return [
        exercise
        for exercise in EXERCISES
        if exercise.muscle_group == muscle_group and level_allows(exercise.level, requested_level)
    ]


def exercises_for_display(muscle_group: str, requested_level: Level) -> list[ExerciseSpec]:
    """动作面板的「新手/老手」列表。

    与 ``exercises_for_group`` 不同：老手面板只显示纯老手/通用动作，不把俯卧撑
    这类新手动作混进「老手动作」列表。计划生成仍然允许老手使用基础动作。
    """
    allowed = ("beginner", "all") if requested_level == "beginner" else ("experienced", "all")
    return [
        exercise
        for exercise in EXERCISES
        if exercise.muscle_group == muscle_group and exercise.level in allowed
    ]


def exercise_option_payload(exercise: ExerciseSpec) -> dict:
    """把动作转成前端动作列表需要的字段。"""
    return {
        "name": exercise.name,
        "equipment": exercise.equipment,
        "is_compound": exercise.is_compound,
        "default_sets": exercise.default_sets,
        "default_reps": exercise.default_reps,
        "rest_seconds": exercise.rest_seconds,
        "description": exercise.description,
    }


def muscle_catalog_payload() -> dict:
    """构造 GET /plan/muscles 的响应体。"""
    groups = []
    for group in MUSCLE_GROUPS:
        beginner = [exercise_option_payload(exercise) for exercise in exercises_for_display(group.name, "beginner")]
        experienced = [exercise_option_payload(exercise) for exercise in exercises_for_display(group.name, "experienced")]
        groups.append(
            {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "exercises": {"beginner": beginner, "experienced": experienced},
            }
        )
    return {"groups": groups}
