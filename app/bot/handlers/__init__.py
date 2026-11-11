from aiogram import Router

from app.bot.handlers import billing, chat, common, models


def setup_routers() -> Router:
    root = Router(name="root")
    # порядок важен: промокод-состояние и команды идут раньше свободного текста
    root.include_router(common.router)
    root.include_router(billing.router)
    root.include_router(models.router)
    root.include_router(chat.router)
    return root
