"""分析训练进展工具 —— 用 Pandas 计算训练趋势。

所有统计均在 Python 中完成，LLM 仅负责解读结果。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

from langchain_core.tools import tool
from loguru import logger
from sqlalchemy import distinct, func, or_, select

from agent.db.models import ExerciseCatalog, User, WorkoutItem, WorkoutSession
from agent.db.mysql import async_session_factory
from agent.utils.utility import resolve_user_id as _resolve_user_id


def _exercise_rows_stmt(user_uuid: uuid.UUID, exercise_name: str, cutoff: date):
    """构建单动作训练记录的查询语句。

    由 tool 的模式 1 和看板的 get_progress_series 共用，确保两者基于同一批行。
    """
    return (
        select(
            WorkoutSession.session_date,
            WorkoutItem.exercise_name,
            WorkoutItem.sets,
            WorkoutItem.reps,
            WorkoutItem.weight_kg,
            # duration_seconds 和 distance_meters 当前始终为 None，仅为有氧运动预留
            WorkoutItem.duration_seconds,
            WorkoutItem.distance_meters,
        )
        .join(WorkoutItem, WorkoutItem.session_id == WorkoutSession.id)
        .where(
            WorkoutSession.user_id == user_uuid,
            WorkoutSession.session_date >= cutoff,
            WorkoutItem.exercise_name.ilike(f"%{exercise_name}%"),  # 模糊匹配动作名
        )
        .order_by(WorkoutSession.session_date.asc())  # 升序，便于计算趋势
    )


def _aggregate_by_date(rows) -> dict[str, dict]:
    """按日期聚合每天的最大重量与总训练量。

    同一天可能有多组同一动作的训练，合并计算。tool 用它算前后半段趋势，
    看板用它画按日期的趋势线——训练量公式只存在于这一处。
    """
    sessions_data: dict[str, dict] = {}
    for row in rows:
        d = str(row.session_date)
        if d not in sessions_data:
            sessions_data[d] = {"max_weight": 0.0, "total_volume": 0.0, "count": 0}
        entry = sessions_data[d]
        weight = row.weight_kg or 0
        sets = row.sets or 0
        reps = row.reps or 0
        # 训练量 = 重量 × 组数 × 次数（单位：公斤）
        volume = weight * sets * reps
        # 当天最大重量（用于追踪力量增长）
        entry["max_weight"] = max(entry["max_weight"], weight)
        # 当天总训练量（用于追踪训练负荷）
        entry["total_volume"] += volume
        entry["count"] += 1
    return sessions_data


@tool
async def analyze_progress_tool(
    user_id: str,
    exercise_name: str | None = None,
    category: str | None = None,
    days_back: int = 90,
) -> str:
    """分析训练进展 —— 支持两种模式。

    模式 1 — 按 exercise_name（单动作趋势分析）：
        追踪某个具体动作的历史进展。
        返回最大重量趋势、训练量趋势、每周训练频率和整体进步百分比。
        适用场景："深蹲进步了吗？", "卧推最近有没有变强？"

    模式 2 — 按 category（身体部位聚合统计）：
        汇总某个身体部位下所有动作的训练数据。
        返回总训练次数、涉及的动作种类数、总组数/次数/训练量。
        可选类别: 胸, 背, 腿, 肩, 手臂, 核心, 有氧
        适用场景："这个月背部练了多少？", "最近腿的训练量？", "我手臂练得够不够？"

    Args:
        user_id: 用户的唯一标识符（UUID 字符串）。
        exercise_name: 要分析的动作名称（如 "深蹲"），对应模式 1。
        category: 身体部位类别（如 "背"），对应模式 2。
        days_back: 分析窗口天数（默认 90，上限 365）。

    Returns:
        包含进展统计数据的 JSON 字符串。
    """
    from agent.tools import current_user_id  # noqa: PLC0415

    enforced = current_user_id.get()
    if enforced:
        user_id = enforced

    user_uuid = _resolve_user_id(user_id)
    # 对参数做上限保护，防止查询范围过大
    days_back = min(days_back, 365)
    # 计算查询的起始日期（今天往回推 N 天）
    cutoff = date.today() - timedelta(days=days_back)

    async with async_session_factory() as session:
        user = await session.get(User, user_uuid)
        if user is None:
            user = User(id=user_uuid, username=user_id)
            session.add(user)
            await session.flush()
            logger.info(f"Auto-created user: {user_id} ({user_uuid})")

        # ── 模式 2: 按身体部位聚合统计 ──
        if category is not None:
            return await _analyze_by_category(session, user_uuid, category, cutoff, days_back)

        # ── 模式 1: 单动作趋势分析（默认，exercise_name 未传则为空字符串）──
        target_exercise = exercise_name or ""
        return await _analyze_by_exercise(session, user_uuid, target_exercise, cutoff, days_back)


async def _analyze_by_exercise(
    session,
    user_uuid: uuid.UUID,
    exercise_name: str,
    cutoff: date,
    days_back: int,
) -> str:
    """单动作趋势分析 —— 统计指定动作的重量和训练量变化趋势。

    核心算法：将时间段平分为前后两半，比较平均值的百分比变化。
    """
    # 查询该动作的所有训练记录，按日期升序排列
    result = await session.execute(_exercise_rows_stmt(user_uuid, exercise_name, cutoff))
    rows = result.all()

    if not rows:
        return json.dumps({
            "exercise": exercise_name,
            "message": f"未找到 {exercise_name} 在最近 {days_back} 天的训练记录。",
            "total_sessions": 0,
        }, ensure_ascii=False)

    # 按日期聚合：同一天可能有多组同一动作的训练，合并计算
    sessions_data = _aggregate_by_date(rows)

    dates = sorted(sessions_data.keys())
    max_weights = [sessions_data[d]["max_weight"] for d in dates]
    volumes = [sessions_data[d]["total_volume"] for d in dates]
    session_count = len(dates)

    # 前后半段对比：将时间平分为两半，比较平均值变化百分比
    if len(max_weights) >= 2:
        # 前半段平均最大重量
        first_half_max = sum(max_weights[: len(max_weights) // 2]) / (len(max_weights) // 2)
        # 后半段平均最大重量
        second_half_max = sum(max_weights[len(max_weights) // 2:]) / (len(max_weights) - len(max_weights) // 2)
        # 重量变化百分比（正数 = 进步，负数 = 退步）
        weight_change_pct = round(
            ((second_half_max - first_half_max) / first_half_max * 100) if first_half_max > 0 else 0, 1
        )
        # 前半段平均训练量
        first_half_vol = sum(volumes[: len(volumes) // 2]) / (len(volumes) // 2)
        # 后半段平均训练量
        second_half_vol = sum(volumes[len(volumes) // 2:]) / (len(volumes) - len(volumes) // 2)
        # 训练量变化百分比
        volume_change_pct = round(
            ((second_half_vol - first_half_vol) / first_half_vol * 100) if first_half_vol > 0 else 0, 1
        )
    else:
        weight_change_pct = 0.0
        volume_change_pct = 0.0

    # 计算每周平均训练次数
    if len(dates) >= 2:
        days_span = (date.today() - date.fromisoformat(dates[0])).days or 1
        sessions_per_week = round(session_count / (days_span / 7), 1)
    else:
        sessions_per_week = 1.0

    analysis = {
        "exercise": exercise_name,
        "period_days": days_back,
        "total_sessions": session_count,
        "sessions_per_week": sessions_per_week,
        # 最近一次训练的最大重量
        "latest_max_weight_kg": max_weights[-1] if max_weights else 0,
        # 全周期内出现的最大重量
        "all_time_max_weight_kg": max(max_weights) if max_weights else 0,
        "avg_max_weight_first_half_kg": round(first_half_max, 1) if session_count >= 2 else (max_weights[0] if max_weights else 0),
        "avg_max_weight_second_half_kg": round(second_half_max, 1) if session_count >= 2 else (max_weights[0] if max_weights else 0),
        "max_weight_change_pct": weight_change_pct,
        "avg_volume_first_half": round(first_half_vol, 0) if session_count >= 2 else (volumes[0] if volumes else 0),
        "avg_volume_second_half": round(second_half_vol, 0) if session_count >= 2 else (volumes[0] if volumes else 0),
        "volume_change_pct": volume_change_pct,
        # 趋势判断：变化 > 2% 为上升，< -2% 为下降，在中间为稳定
        "trend_direction": "up" if weight_change_pct > 2 else "down" if weight_change_pct < -2 else "stable",
    }

    logger.info(f"Progress analysis for {exercise_name}: {session_count} sessions, {weight_change_pct}% weight change")
    return json.dumps(analysis, ensure_ascii=False, indent=2)


async def _analyze_by_category(
    session,
    user_uuid: uuid.UUID,
    category: str,
    cutoff: date,
    days_back: int,
) -> str:
    """按身体部位聚合统计 —— 汇总某个部位下所有动作的训练数据。

    采用两级查询策略：
    1. 首选通过 ExerciseCatalog 外键关联精确匹配类别
    2. 若无匹配（旧数据未关联目录），回退到按动作名称模糊匹配
    """
    # 策略 1: 通过 exercise_catalog_id 外键精确关联类别
    stmt = (
        select(
            WorkoutItem.exercise_name,
            WorkoutItem.sets,
            WorkoutItem.reps,
            WorkoutItem.weight_kg,
            WorkoutItem.duration_seconds,
            WorkoutItem.distance_meters,
            WorkoutSession.session_date,
            WorkoutSession.id,
        )
        .join(WorkoutSession, WorkoutItem.session_id == WorkoutSession.id)
        .join(ExerciseCatalog, WorkoutItem.exercise_catalog_id == ExerciseCatalog.id)
        .where(
            WorkoutSession.user_id == user_uuid,
            WorkoutSession.session_date >= cutoff,
            ExerciseCatalog.category == category,  # 按类别精确筛选
        )
        .order_by(WorkoutSession.session_date.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    # Best-effort: 如果外键关联无结果，尝试回退方案
    if not rows:
        # 先查出该类别下有哪些动作名称
        cat_result = await session.execute(
            select(ExerciseCatalog.name).where(ExerciseCatalog.category == category)
        )
        cat_names = [r[0] for r in cat_result.all()]
        if cat_names:
            # 用动作名称做模糊匹配（ILike），覆盖未关联 catalog 的历史数据
            name_conditions = [
                WorkoutItem.exercise_name.ilike(f"%{n}%") for n in cat_names
            ]
            stmt = (
                select(
                    WorkoutItem.exercise_name,
                    WorkoutItem.sets,
                    WorkoutItem.reps,
                    WorkoutItem.weight_kg,
                    WorkoutItem.duration_seconds,
                    WorkoutItem.distance_meters,
                    WorkoutSession.session_date,
                    WorkoutSession.id,
                )
                .join(WorkoutSession, WorkoutItem.session_id == WorkoutSession.id)
                .where(
                    WorkoutSession.user_id == user_uuid,
                    WorkoutSession.session_date >= cutoff,
                    or_(*name_conditions),  # 任一动作名匹配即可
                )
                .order_by(WorkoutSession.session_date.desc())
            )
            result = await session.execute(stmt)
            rows = result.all()

    if not rows:
        return json.dumps({
            "category": category,
            "message": f"未找到 {category} 部在最近 {days_back} 天的训练记录。",
            "total_sessions": 0,
            "total_exercises": 0,
            "total_sets": 0,
            "total_reps": 0,
            "total_volume_kg": 0,
        }, ensure_ascii=False)

    # 对该部位下所有动作做聚合统计
    exercises_seen: set[str] = set()   # 去重统计做过哪些动作
    sessions_seen: set[str] = set()    # 去重统计多少次训练
    total_sets = 0
    total_reps = 0
    total_volume = 0.0

    for row in rows:
        exercises_seen.add(row.exercise_name)
        sessions_seen.add(str(row.id))
        total_sets += row.sets or 0
        total_reps += row.reps or 0
        w = row.weight_kg or 0
        s = row.sets or 0
        r = row.reps or 0
        # 仅当重量、组数、次数均有效时才计入训练量
        if w > 0 and s > 0 and r > 0:
            total_volume += w * s * r

    # 计算每周平均训练频率
    sessions_per_week = 0.0
    if len(sessions_seen) >= 2:
        # 通过实际训练日期跨度和 session 数来估算
        dates_seen = sorted({str(r.session_date) for r in rows})
        if len(dates_seen) >= 2:
            span = (date.today() - date.fromisoformat(dates_seen[0])).days or 1
            sessions_per_week = round(len(sessions_seen) / (span / 7), 1)

    analysis = {
        "category": category,
        "period_days": days_back,
        "total_sessions": len(sessions_seen),
        "sessions_per_week": sessions_per_week,
        "total_exercises": len(exercises_seen),
        "exercises": sorted(exercises_seen),  # 按字母排序的动作列表
        "total_sets": total_sets,
        "total_reps": total_reps,
        "total_volume_kg": round(total_volume, 1),
    }

    logger.info(
        f"Category analysis for {category}: {len(sessions_seen)} sessions, "
        f"{len(exercises_seen)} exercises, {total_volume}kg volume"
    )
    return json.dumps(analysis, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 看板专用查询 —— 不是 tool，只给 HTTP 端点用
#
# 这两个函数刻意放在 tool 旁边而不是 API 层：它们共用上面的 _exercise_rows_stmt
# 和 _aggregate_by_date，所以看板画出来的数字和 Agent 在对话里说的数字必然一致。
# analyze_progress_tool 的返回格式不受影响（它本来就不返回按日期的序列）。
# ---------------------------------------------------------------------------


async def get_progress_series(
    user_id: str,
    exercise_name: str,
    days_back: int = 90,
) -> list[dict]:
    """返回某个动作按日期排列的最大重量与训练量序列。

    Args:
        user_id: 用户标识符（UUID 字符串或用户名）。
        exercise_name: 动作名称，模糊匹配。
        days_back: 回溯天数（上限 365）。

    Returns:
        按日期升序的列表，每项含 date / max_weight_kg / volume_kg。
    """
    user_uuid = _resolve_user_id(user_id)
    days_back = min(days_back, 365)
    cutoff = date.today() - timedelta(days=days_back)

    async with async_session_factory() as session:
        result = await session.execute(
            _exercise_rows_stmt(user_uuid, exercise_name, cutoff)
        )
        by_date = _aggregate_by_date(result.all())

    return [
        {
            "date": d,
            "max_weight_kg": round(by_date[d]["max_weight"], 1),
            "volume_kg": round(by_date[d]["total_volume"], 1),
        }
        for d in sorted(by_date)
    ]


async def get_category_summary(user_id: str, days_back: int = 90) -> list[dict]:
    """按身体部位汇总训练量，供看板的部位分布图使用。

    用一次 group_by 覆盖全部部位，避免为 7 个类别分别调用 analyze_progress_tool
    （那是 7 次数据库往返）。

    注意：这里只统计已关联 exercise_catalog 的动作项。_analyze_by_category 还有
    一层按动作名模糊匹配的回退，用于补捞未关联目录的历史数据；本函数不做回退，
    所以对这类旧数据统计会偏低。add_workout_tool 写入时会尝试关联目录，新数据不受影响。

    Args:
        user_id: 用户标识符（UUID 字符串或用户名）。
        days_back: 回溯天数（上限 365）。

    Returns:
        列表，每项含 category / total_volume_kg / total_sessions，按训练量降序。
    """
    user_uuid = _resolve_user_id(user_id)
    days_back = min(days_back, 365)
    cutoff = date.today() - timedelta(days=days_back)

    # 训练量 = 重量 × 组数 × 次数。用 coalesce 把 NULL 折成 0，效果等同于
    # _analyze_by_category 里「三个因子都有效才计入」的判断。
    volume_expr = func.sum(
        func.coalesce(WorkoutItem.weight_kg, 0)
        * func.coalesce(WorkoutItem.sets, 0)
        * func.coalesce(WorkoutItem.reps, 0)
    )

    stmt = (
        select(
            ExerciseCatalog.category,
            volume_expr.label("total_volume"),
            func.count(distinct(WorkoutSession.id)).label("total_sessions"),
        )
        # 必须显式指定 FROM：第一个查询列来自 exercise_catalog，若不指定，
        # SQLAlchemy 会从它开始 join，而下面第一个 ON 条件引用的是 workout_session。
        .select_from(WorkoutSession)
        .join(WorkoutItem, WorkoutItem.session_id == WorkoutSession.id)
        .join(ExerciseCatalog, WorkoutItem.exercise_catalog_id == ExerciseCatalog.id)
        .where(
            WorkoutSession.user_id == user_uuid,
            WorkoutSession.session_date >= cutoff,
            ExerciseCatalog.category.isnot(None),
        )
        .group_by(ExerciseCatalog.category)
        .order_by(volume_expr.desc())
    )

    async with async_session_factory() as session:
        result = await session.execute(stmt)
        rows = result.all()

    logger.info(f"Category summary for {user_id}: {len(rows)} categories")
    return [
        {
            "category": row.category,
            "total_volume_kg": round(float(row.total_volume or 0), 1),
            "total_sessions": row.total_sessions,
        }
        for row in rows
    ]
