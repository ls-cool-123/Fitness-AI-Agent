"""训练计划的 MySQL 读写服务。

API 路由和 Agent 工具都走这一层，避免「API 直存 / 工具直存」两套逻辑分叉。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from agent.db.models import TrainingPlan, User
from agent.db.mysql import async_session_factory
from agent.plans.generator import apply_swaps, plan_summary, refresh_alternatives
from agent.plans.normalize import normalize_experience, normalize_split
from agent.utils.utility import resolve_user_id

_MAX_LIST_LIMIT = 50


def _username(user_id: str, user_uuid: uuid.UUID) -> str:
    """与训练记录工具保持同一套用户名规则。"""
    try:
        uuid.UUID(user_id)
    except ValueError:
        return user_id
    return f"user-{user_uuid.hex[:8]}"


async def _ensure_user(session, user_id: str, user_uuid: uuid.UUID) -> User:  # noqa: ANN001
    """确保用户存在；不存在时按与训练记录一致的方式创建。"""
    user = await session.get(User, user_uuid)
    if user is None:
        user = User(id=user_uuid, username=_username(user_id, user_uuid))
        session.add(user)
        await session.flush()
    return user


def _hydrate(plan: dict[str, Any], row: TrainingPlan) -> dict[str, Any]:
    """补齐 plan_data 里可能缺失的元字段，保证前端总能拿到稳定结构。"""
    hydrated = dict(plan)
    hydrated.setdefault("plan_id", str(row.id))
    hydrated.setdefault("source", row.source)
    hydrated.setdefault("created_at", row.created_at.isoformat() if row.created_at else "")
    return refresh_alternatives(hydrated)


async def save_plan(user_id: str, plan: dict[str, Any], source: str) -> dict[str, Any]:
    """保存一份计划并回填 plan_id/created_at/source。

    Args:
        user_id: 用户标识（UUID 或用户名）。
        plan: ``build_plan`` 的输出。
        source: anatomy / chat。

    Returns:
        带回 plan_id/created_at/source 的计划 dict。
    """
    user_uuid = resolve_user_id(user_id)
    plan_id = uuid.uuid4()
    created_at = datetime.now(UTC)
    stored = dict(plan)
    stored["plan_id"] = str(plan_id)
    stored["source"] = source
    stored["created_at"] = created_at.isoformat()

    experience = normalize_experience(stored.get("experience"))
    split = normalize_split(stored.get("split"))
    if experience is None or split is None:
        raise ValueError("计划缺少有效的 experience/split 字段。")

    async with async_session_factory() as session:
        await _ensure_user(session, user_id, user_uuid)
        row = TrainingPlan(
            id=plan_id,
            user_id=user_uuid,
            name=str(stored.get("name") or "训练计划"),
            goal=str(stored.get("goal") or "增肌"),
            experience=experience,
            split_type=split,
            source=source,
            focus_muscles=list(stored.get("focus_muscles") or []),
            plan_data=stored,
            created_at=created_at,
        )
        session.add(row)
        await session.commit()
    return stored


async def list_plans(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """返回计划摘要，最新的在前。用户不存在时返回空列表。"""
    user_uuid = resolve_user_id(user_id)
    limit = max(1, min(limit, _MAX_LIST_LIMIT))
    async with async_session_factory() as session:
        result = await session.execute(
            select(TrainingPlan)
            .where(TrainingPlan.user_id == user_uuid)
            .order_by(TrainingPlan.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
        return [
            plan_summary(
                row.plan_data or {},
                plan_id=str(row.id),
                source=row.source,
                created_at=row.created_at.isoformat() if row.created_at else "",
            )
            for row in rows
        ]


async def get_plan(user_id: str, plan_id: str) -> dict[str, Any] | None:
    """按 id 取计划，同时校验归属；查不到/不属于该用户返回 None。"""
    user_uuid = resolve_user_id(user_id)
    try:
        plan_uuid = uuid.UUID(str(plan_id))
    except (ValueError, AttributeError):
        return None
    async with async_session_factory() as session:
        row = await session.get(TrainingPlan, plan_uuid)
        if row is None or row.user_id != user_uuid:
            return None
        return _hydrate(row.plan_data or {}, row)


async def get_latest_plan(user_id: str) -> dict[str, Any] | None:
    """取用户最新创建的计划；用于 AI 对话里省略 plan_id 的修改请求。"""
    user_uuid = resolve_user_id(user_id)
    async with async_session_factory() as session:
        result = await session.execute(
            select(TrainingPlan)
            .where(TrainingPlan.user_id == user_uuid)
            .order_by(TrainingPlan.created_at.desc())
            .limit(1)
        )
        row = result.scalars().first()
        if row is None:
            return None
        return _hydrate(row.plan_data or {}, row)


async def update_plan_data(user_id: str, plan_id: str, plan: dict[str, Any]) -> dict[str, Any] | None:
    """覆盖保存一份已存在计划的正文；计划不存在/不属于该用户返回 None。"""
    user_uuid = resolve_user_id(user_id)
    try:
        plan_uuid = uuid.UUID(str(plan_id))
    except (ValueError, AttributeError):
        return None
    async with async_session_factory() as session:
        row = await session.get(TrainingPlan, plan_uuid)
        if row is None or row.user_id != user_uuid:
            return None
        updated = dict(plan)
        updated["plan_id"] = str(row.id)
        updated["source"] = row.source
        updated["created_at"] = row.created_at.isoformat() if row.created_at else ""
        row.plan_data = updated
        row.name = str(updated.get("name") or row.name)
        row.goal = str(updated.get("goal") or row.goal or "增肌")
        row.experience = str(updated.get("experience") or row.experience)
        row.split_type = str(updated.get("split") or row.split_type)
        row.focus_muscles = list(updated.get("focus_muscles") or [])
        await session.commit()
        return updated


async def update_plan_swaps(user_id: str, plan_id: str, swaps: object) -> dict[str, Any] | None:
    """换动作并保存；计划不存在/不属于该用户返回 None。

    Raises:
        PlanValidationError: 换动作校验失败，由 API 转成 400。
    """
    user_uuid = resolve_user_id(user_id)
    try:
        plan_uuid = uuid.UUID(str(plan_id))
    except (ValueError, AttributeError):
        return None
    async with async_session_factory() as session:
        row = await session.get(TrainingPlan, plan_uuid)
        if row is None or row.user_id != user_uuid:
            return None
        updated = apply_swaps(row.plan_data or {}, swaps, allow_level_mismatch=True)
        updated["plan_id"] = str(row.id)
        updated["source"] = row.source
        updated["created_at"] = row.created_at.isoformat() if row.created_at else ""
        row.plan_data = updated
        await session.commit()
        return updated


async def delete_plan(user_id: str, plan_id: str) -> bool:
    """删除计划并校验归属；成功返回 True，查不到/不属于该用户返回 False。"""
    user_uuid = resolve_user_id(user_id)
    try:
        plan_uuid = uuid.UUID(str(plan_id))
    except (ValueError, AttributeError):
        return False
    async with async_session_factory() as session:
        row = await session.get(TrainingPlan, plan_uuid)
        if row is None or row.user_id != user_uuid:
            return False
        await session.delete(row)
        await session.commit()
        return True
