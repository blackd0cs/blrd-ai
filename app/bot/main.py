from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from app.bot.handlers import setup_routers
from app.bot.middlewares import UserMiddleware
from app.core.catalog import catalog
from app.core.config import settings
from app.core.db import init_db
from app.services.anymodel import anymodel

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="new", description="Новый чат"),
    BotCommand(command="model", description="Выбрать нейросеть"),
    BotCommand(command="balance", description="Энергия и тариф"),
    BotCommand(command="pro", description="Подписка Pro"),
    BotCommand(command="promo", description="Ввести промокод"),
    BotCommand(command="stop", description="Прервать ответ"),
    BotCommand(command="help", description="Что умеет бот"),
]


def build() -> tuple[Bot, Dispatcher]:
    if not settings.bot_token:
        raise SystemExit("BOT_TOKEN не задан в .env")

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(UserMiddleware())
    dp.include_router(setup_routers())
    return bot, dp


async def run() -> None:
    await init_db()
    catalog.reload()
    bot, dp = build()

    me = await bot.get_me()
    log.info("бот @%s запущен, моделей: %d", me.username, len(catalog.models()))

    await bot.set_my_commands(COMMANDS)
    if settings.webapp_url.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Приложение", web_app=WebAppInfo(url=settings.webapp_url))
        )
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        log.warning("WEBAPP_URL не https — кнопка Mini App отключена")

    try:
        from app.admin.broadcast import worker  # появится в части 5

        asyncio.create_task(worker(bot))
    except ImportError:
        pass

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await anymodel.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        log.info("бот остановлен")


if __name__ == "__main__":
    main()
