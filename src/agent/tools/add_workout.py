"""添加训练记录工具 — 接收结构化数据直接写入 MySQL。

写库是不可逆操作，因此 Agent 调用路径上会经过一道人工确认（HITL）：

    LLM 解析出动作列表 → interrupt() 暂停 → 前端展示确认卡片
      → 用户确认 → Command(resume=...) → 继续落库

直接在 Agent 图外调用本工具（如 POST /workout/add）不会触发确认，
避免把"用户自己填好表单再提交"也拦一道。
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from langchain_core.tools import tool
from loguru import logger
from sqlalchemy import or_, select

from agent.db.models import ExerciseCatalog, User, WorkoutItem, WorkoutSession
from agent.db.mysql import async_session_factory
from agent.parser.workout_parser import build_workout
from agent.utils.config import config
from agent.utils.utility import get_graph_thread_id as _graph_thread_id
from agent.utils.utility import resolve_user_id


def _looks_like_uuid(s: str) -> bool:
    """判断字符串是否类似 UUID 格式。"""
    try:
        uuid.UUID(s)
        return True
    except (ValueError, AttributeError):
        return False


def _preview_item(exercise: Any) -> dict[str, Any]:
    """把解析结果组装成交互卡片用的预览项。

    ``reps`` 在工具输入里是**总次数**（所有组之和），但确认卡片是按
    "组数 × 每组次数" 展示和编辑的。若直接把 reps 交给前端，5 组 5 次会被
    显示成 "5 组 × 25 次"。因此额外给出 ``reps_per_set``，由前端优先使用。
    """
    sets = exercise.sets or 0
    reps = exercise.reps or 0
    reps_per_set = reps // sets if sets > 0 and reps > 0 else None
    return {
        "name": exercise.name,
        "sets": exercise.sets,
        "reps": exercise.reps,
        "reps_per_set": reps_per_set,
        "weight_kg": exercise.weight_kg,
        "set_details": (
            [detail.model_dump() for detail in exercise.set_details]
            if exercise.set_details
            else None
        ),
        "notes": exercise.notes,
    }


def _normalize_edits(edits: list[dict]) -> list[dict]:
    """把用户在卡片里改过的数值统一成工具输入格式。

    前端按"每组次数"编辑，回传 ``reps_per_set``；工具输入要的是总次数，
    这里换算回去。同时接受直接给 ``reps`` 的调用方，保持向后兼容。
    """
    normalized: list[dict] = []
    for item in edits:
        entry = dict(item)
        reps_per_set = entry.pop("reps_per_set", None)
        if reps_per_set is not None:
            sets = entry.get("sets") or 0
            entry["reps"] = sets * reps_per_set
        normalized.append(entry)
    return normalized


def _request_confirmation(parsed: Any) -> dict[str, Any] | None:
    """在写入前请求用户确认。

    Returns:
        None —— 未启用确认或不在 Agent 图中，调用方直接落库；
        dict —— 用户的选择，形如 ``{"approved": bool, "edits": list | None}``。
    """
    if not config.workout_confirm_enabled or _graph_thread_id() is None:
        return None

    from langgraph.types import interrupt  # noqa: PLC0415

    # 注意：resume 时工具会从头重新执行，所以 interrupt() 之前不能有副作用。
    # 这里只有纯计算（parse），副作用（写库）全部放在 interrupt() 之后。
    decision = interrupt(
        {
            "action": "confirm_workout",
            "message": "即将写入训练记录，请确认解析结果",
            "preview": [_preview_item(exercise) for exercise in parsed.exercises],
        }
    )
    return decision if isinstance(decision, dict) else {"approved": bool(decision)}


@tool
async def add_workout_tool(
    user_id: str,
    exercises: list[dict],
) -> str:
    """记录一次训练，接收结构化动作数据写入数据库。

    当用户用自然语言描述了一次训练（如"今天深蹲 80kg 5 组 5 次"）并要求记录时
    调用此工具。写入前会先请求用户确认，用户取消则不写入。

    每个 dict 需包含:
        - name (str): 动作名称
        - sets (int): 组数
        - reps (int): **总次数**（所有组之和）。"5 组 5 次"要传 sets=5, reps=25，
          不要传每组次数，否则总容量会被算成原来的 1/5
        - weight_kg (float, 可选): 重量（公斤），0 表示自重

    Args:
        user_id: 用户标识符（UUID 字符串或用户名）
        exercises: 结构化训练动作列表

    Returns:
        包含训练记录确认信息的 JSON 字符串
    """
    # 确保 Agent 调用时使用正确的 user_id
    from agent.tools import current_user_id  # noqa: PLC0415

    enforced = current_user_id.get()
    if enforced:
        user_id = enforced

    # 将 user_id 转为 UUID（与查询/分析工具共用同一套确定性映射）
    user_uuid = resolve_user_id(user_id)

    username = user_id if not _looks_like_uuid(user_id) else f"user-{user_uuid.hex[:8]}"

    # 从结构化数据构建 ParsedWorkout
    try:
        parsed = build_workout(exercises)
    except (ValueError, KeyError) as e:
        return json.dumps(
            {"error": f"训练数据格式错误: {e}"},
            ensure_ascii=False,
        )

    # ---- HITL：写库前暂停，等用户确认（仅 Agent 调用路径）----
    decision = _request_confirmation(parsed)
    if decision is not None:
        if not decision.get("approved"):
            logger.info("用户取消了本次训练记录写入")
            return json.dumps(
                {
                    "status": "cancelled",
                    "message": "用户取消了本次记录，未写入任何数据。",
                    "exercises": [exercise.model_dump() for exercise in parsed.exercises],
                },
                ensure_ascii=False,
            )
        # 用户在确认卡片里改了数字，用修正后的数据重新解析
        edits = decision.get("edits")
        if edits:
            try:
                parsed = build_workout(_normalize_edits(edits))
            except (ValueError, KeyError) as e:
                return json.dumps(
                    {"error": f"修改后的训练数据格式错误: {e}"},
                    ensure_ascii=False,
                )

    # 写入数据库
    async with async_session_factory() as session:
        # 确保用户存在
        user = await session.get(User, user_uuid)
        if user is None:
            user = User(id=user_uuid, username=username)
            session.add(user)
            await session.flush()
            logger.info(f"自动创建用户: {username} ({user_uuid})")

        # 创建训练记录
        workout = WorkoutSession(
            user_id=user_uuid,
            session_date=date.today(),
            notes=None,
        )
        session.add(workout)
        await session.flush()

        # 逐项写入训练动作
        items_saved = []
        for ex in parsed.exercises:
            # 查找动作目录匹配项
            catalog_entry = None
            if ex.name:
                result = await session.execute(
                    select(ExerciseCatalog).where(
                        or_(
                            ExerciseCatalog.name.ilike(f"%{ex.name}%"),
                            ExerciseCatalog.alias.contains(ex.name),
                        )
                    )
                )
                catalog_entry = result.scalars().first()

            item = WorkoutItem(
                session_id=workout.id,
                exercise_name=ex.name,
                exercise_catalog_id=catalog_entry.id if catalog_entry else None,
                sets=ex.sets,
                reps=ex.reps if ex.reps and ex.reps > 0 else None,
                weight_kg=ex.weight_kg,
                set_details=[s.model_dump() for s in ex.set_details] if ex.set_details else None,
                duration_seconds=None,
                distance_meters=None,
                notes=ex.notes,
            )
            session.add(item)
            items_saved.append({
                "exercise": ex.name,
                "sets": ex.sets,
                "reps": ex.reps,
                "weight_kg": ex.weight_kg,
                "set_details": [s.model_dump() for s in ex.set_details] if ex.set_details else None,
            })

        await session.commit()

        result = {
            "status": "success",
            "session_id": str(workout.id),
            "date": str(workout.session_date),
            "exercises": items_saved,
        }
        logger.info(f"已保存训练记录 {workout.id}，共 {len(items_saved)} 项动作")
        return json.dumps(result, ensure_ascii=False, indent=2)
