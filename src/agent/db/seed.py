"""在应用启动时向 exercise_catalog 表填充常用健身动作数据。

该脚本在 init_db（建表）之后执行。采用幂等设计——已存在的动作条目会被跳过，
因此重复启动不会产生重复数据。

动作元数据统一维护在 ``agent.plans.catalog``：训练计划生成器需要水平/器械/
复合动作等字段，而这张表只保留训练记录匹配所需的「名称 + 分类 + 别名」。
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy import select

from agent.db.models import ExerciseCatalog
from agent.db.mysql import async_session_factory
from agent.plans.catalog import EXERCISES

# 每个条目格式: (标准中文名称, 肌群分类, [别名列表])
# 别名统一使用小写，便于精确匹配查询。
_EXERCISES = [(exercise.name, exercise.category, list(exercise.aliases)) for exercise in EXERCISES]


async def seed_exercise_catalog() -> None:
    """应用首次启动时向 exercise_catalog 表填充预定义动作条目。

    幂等设计：插入前先查询该动作名是否已存在，已存在则跳过。
    因此无论重启多少次，都不会产生重复数据。

    执行时机：在 init_db() 建表之后调用。新条目会被批量提交到一个事务中。
    """
    async with async_session_factory() as session:
        inserted = 0
        for name, category, aliases in _EXERCISES:
            # 查询是否已存在同名动作，避免重复插入
            existing = await session.execute(
                select(ExerciseCatalog.id).where(ExerciseCatalog.name == name)
            )
            if existing.scalars().first():
                continue  # 已存在，跳过

            session.add(ExerciseCatalog(name=name, category=category, alias=aliases))
            inserted += 1

        if inserted:
            await session.commit()
            logger.info(f"Seeded exercise catalog: {inserted} new entries")
        else:
            logger.info("Exercise catalog already seeded — skipped")
