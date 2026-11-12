import asyncio
import logging
import re
import aiosqlite
import httpx
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = "9263325331:AAHKd5yXUuEYqoeHhpJl1JpEwtroz0C2IS0"
CHECK_INTERVAL = 20  # Интервал фоновой проверки новых лотов (сек)
DB_PATH = "fragment_parser.db"
ITEMS_PER_PAGE = 8  # Сколько кнопок-юзернеймов показывать на одной странице списка

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Состояние для ручного ввода цены "От и До"
class PriceFilterState(StatesGroup):
    waiting_for_range = State()


# ================= БАЗА ДАННЫХ (SQLite) =================
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица настроек пользователя
        await db.execute("""
                         CREATE TABLE IF NOT EXISTS user_settings
                         (
                             user_id
                             INTEGER
                             PRIMARY
                             KEY,
                             min_price
                             REAL
                             DEFAULT
                             12.0,
                             max_price
                             REAL
                             DEFAULT
                             16.0,
                             is_active
                             INTEGER
                             DEFAULT
                             1
                         )
                         """)
        # Таблица уже просмотренных лотов (чтобы не дублировать уведомления)
        await db.execute("""
                         CREATE TABLE IF NOT EXISTS seen_items
                         (
                             unique_key
                             TEXT
                             PRIMARY
                             KEY,
                             username
                             TEXT,
                             price
                             REAL,
                             market_type
                             TEXT,
                             url
                             TEXT
                         )
                         """)
        await db.commit()


async def get_user_settings(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT min_price, max_price, is_active FROM user_settings WHERE user_id = ?",
                (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                await db.execute(
                    "INSERT INTO user_settings (user_id, min_price, max_price, is_active) VALUES (?, 12.0, 16.0, 1)",
                    (user_id,),
                )
                await db.commit()
                return {"min_price": 12.0, "max_price": 16.0, "is_active": True}
            return {"min_price": row[0], "max_price": row[1], "is_active": bool(row[2])}


async def update_user_range(user_id: int, min_p: float, max_p: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO user_settings (user_id, min_price, max_price, is_active) VALUES (?, ?, ?, 1) "
            "ON CONFLICT(user_id) DO UPDATE SET min_price = excluded.min_price, max_price = excluded.max_price",
            (user_id, min_p, max_p),
        )
        await db.commit()


async def toggle_user_active(user_id: int) -> bool:
    settings = await get_user_settings(user_id)
    new_state = 0 if settings["is_active"] else 1
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE user_settings SET is_active = ? WHERE user_id = ?",
            (new_state, user_id),
        )
        await db.commit()
    return bool(new_state)


async def get_all_active_users() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT user_id, min_price, max_price FROM user_settings WHERE is_active = 1"
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"user_id": r[0], "min_price": r[1], "max_price": r[2]} for r in rows]


# ================= ПАРСЕР FRAGMENT =================
async def fetch_fragment_page(client: httpx.AsyncClient, filter_type: str, sort_type: str = "listed") -> list[dict]:
    """
    filter_type: 'sale' (В продаже) или 'auction' (Аукцион)
    sort_type: 'listed' (Новые) или 'price_asc' (Дешевые сверху)
    """
    url = f"https://fragment.com/?sort={sort_type}&filter={filter_type}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    try:
        resp = await client.get(url, headers=headers, timeout=12.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        logging.error(f"Ошибка парсинга Fragment ({filter_type}, {sort_type}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    rows = soup.select("tr.tm-row-selectable")
    items = []

    for row in rows:
        # 1. Юзернейм
        name_el = row.select_one(".table-cell-value.tm-value")
        if not name_el:
            continue
        username = name_el.text.strip().lstrip("@")

        # 2. Цена в TON (Gram)
        price_el = row.select_one(".table-cell-value.tm-value.icon-before.icon-ton")
        if not price_el:
            continue
        price_clean = re.sub(r"[^\d.]", "", price_el.text.strip())
        if not price_clean:
            continue
        price = float(price_clean)

        # 3. Тип размещения
        m_type = "Аукцион 🔨" if filter_type == "auction" else "Продажа 💰"

        items.append({
            "unique_key": f"{username}_{filter_type}_{price}",
            "username": username,
            "price": price,
            "type": m_type,
            "url": f"https://fragment.com/username/{username}",
        })

    return items


async def get_current_matching_items(min_p: float, max_p: float) -> list[dict]:
    """
    Собирает актуальный список юзернеймов с Fragment (сразу проверяет и новые, и дешевые лоты)
    и плюс подтягивает найденные ранее лоты из локальной БД в заданном бюджете.
    """
    collected = {}

    async with httpx.AsyncClient() as client:
        # Запрашиваем параллельно: свежие и отсортированные по возрастанию цены
        tasks = [
            fetch_fragment_page(client, "sale", "listed"),
            fetch_fragment_page(client, "sale", "price_asc"),
            fetch_fragment_page(client, "auction", "listed"),
            fetch_fragment_page(client, "auction", "price_asc"),
        ]
        results = await asyncio.gather(*tasks)

        for batch in results:
            for item in batch:
                if min_p <= item["price"] <= max_p:
                    collected[item["username"]] = item

    # Дополняем тем, что бот уже успел заметить ранее в кэше
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
                "SELECT username, price, market_type, url FROM seen_items WHERE price BETWEEN ? AND ? ORDER BY rowid DESC LIMIT 50",
                (min_p, max_p),
        ) as cursor:
            rows = await cursor.fetchall()
            for r in rows:
                uname = r[0]
                if uname not in collected:
                    collected[uname] = {
                        "username": uname,
                        "price": r[1],
                        "type": r[2],
                        "url": r[3],
                    }

    # Сортируем по возрастанию цены
    sorted_list = sorted(collected.values(), key=lambda x: x["price"])
    return sorted_list


# ================= КЛАВИАТУРЫ =================
def build_main_menu(settings: dict) -> InlineKeyboardMarkup:
    status_btn = "🟢 Уведомления: ВКЛ" if settings["is_active"] else "🔴 Уведомления: ВЫКЛ"
    min_p, max_p = settings["min_price"], settings["max_price"]

    kb = [
        [
            InlineKeyboardButton(
                text=f"📋 Открыть список в продаже ({min_p:g}–{max_p:g} TON)",
                callback_data="list_page_0",
            )
        ],
        [
            InlineKeyboardButton(text="✏️ Задать свою цену (От и До)", callback_data="custom_price")
        ],
        [
            InlineKeyboardButton(text="12 – 16 TON", callback_data="quick_12_16"),
            InlineKeyboardButton(text="5 – 12 TON", callback_data="quick_5_12"),
            InlineKeyboardButton(text="16 – 35 TON", callback_data="quick_16_35"),
        ],
        [InlineKeyboardButton(text=status_btn, callback_data="toggle_notify")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def build_items_list_kb(items: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """Генерирует список кнопок-ссылок на юзернеймы с пагинацией"""
    total_pages = max(1, (len(items) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    current_slice = items[start:end]

    kb = []
    # Каждая кнопка — прямая ссылка на юзернейм на Fragment
    for item in current_slice:
        btn_text = f"@{item['username']} — {item['price']:g} TON ({item['type']})"
        kb.append([InlineKeyboardButton(text=btn_text, url=item["url"])])

    # Кнопки навигации (Листалка)
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"list_page_{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"Стр. {page + 1}/{total_pages}", callback_data="noop"))
    if end < len(items):
        nav_row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"list_page_{page + 1}"))

    if len(items) > 0:
        kb.append(nav_row)

    kb.append([
        InlineKeyboardButton(text="🔄 Обновить список", callback_data=f"list_page_{page}"),
        InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ================= ФОНОВЫЙ МОНИТОРИНГ =================
async def monitor_worker():
    async with httpx.AsyncClient() as client:
        # Первичное заполнение базы при старте (чтобы не слать старые лоты как новые)
        logging.info("Первичная синхронизация с Fragment...")
        init_sale = await fetch_fragment_page(client, "sale", "listed")
        init_auc = await fetch_fragment_page(client, "auction", "listed")

        async with aiosqlite.connect(DB_PATH) as db:
            for item in init_sale + init_auc:
                await db.execute(
                    "INSERT OR IGNORE INTO seen_items (unique_key, username, price, market_type, url) VALUES (?, ?, ?, ?, ?)",
                    (item["unique_key"], item["username"], item["price"], item["type"], item["url"]),
                )
            await db.commit()
        logging.info("Синхронизация завершена! Мониторинг новых лотов запущен.")

        while True:
            await asyncio.sleep(CHECK_INTERVAL)
            active_users = await get_all_active_users()
            if not active_users:
                continue

            new_items = []
            for f_type in ("sale", "auction"):
                fetched = await fetch_fragment_page(client, f_type, "listed")
                async with aiosqlite.connect(DB_PATH) as db:
                    for item in fetched:
                        async with db.execute(
                                "SELECT 1 FROM seen_items WHERE unique_key = ?", (item["unique_key"],)
                        ) as cur:
                            exists = await cur.fetchone()

                        if not exists:
                            await db.execute(
                                "INSERT INTO seen_items (unique_key, username, price, market_type, url) VALUES (?, ?, ?, ?, ?)",
                                (item["unique_key"], item["username"], item["price"], item["type"], item["url"]),
                            )
                            new_items.append(item)
                    await db.commit()

            # Рассылаем новые лоты тем пользователям, чей фильтр "От и До" подходит
            for item in new_items:
                for u in active_users:
                    if u["min_price"] <= item["price"] <= u["max_price"]:
                        msg_text = (
                            f"🔔 <b>Новый юзернейм в твоём диапазоне!</b>\n\n"
                            f"👤 Юзернейм: <code>@{item['username']}</code>\n"
                            f"🏷 Формат: {item['type']}\n"
                            f"💎 Цена: <b>{item['price']:g} TON (Gram)</b>"
                        )
                        link_kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(text=f"🔗 Открыть @{item['username']} на Fragment", url=item["url"])]
                        ])
                        try:
                            await bot.send_message(
                                chat_id=u["user_id"],
                                text=msg_text,
                                reply_markup=link_kb,
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            logging.error(f"Ошибка отправки пользователю {u['user_id']}: {e}")


# ================= ХЭНДЛЕРЫ TELEGRAM БОТА =================
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    settings = await get_user_settings(message.from_user.id)
    text = (
        f"👋 <b>Парсер Fragment (TON / Gram)</b>\n\n"
        f"🎯 Твой текущий фильтр цены: <b>от {settings['min_price']:g} до {settings['max_price']:g} TON</b>\n\n"
        f"• Бот автоматически присылает новые лоты, попадающие в этот бюджет.\n"
        f"• Нажми <b>«Открыть список в продаже»</b>, чтобы посмотреть доступные сейчас варианты кнопками."
    )
    await message.answer(text, reply_markup=build_main_menu(settings), parse_mode="HTML")


@dp.callback_query(F.data == "back_to_menu")
async def cb_back_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    settings = await get_user_settings(callback.from_user.id)
    text = (
        f"⚙️ <b>Панель управления парсером Fragment</b>\n\n"
        f"🎯 Текущий фильтр цены: <b>от {settings['min_price']:g} до {settings['max_price']:g} TON</b>"
    )
    await callback.message.edit_text(text, reply_markup=build_main_menu(settings), parse_mode="HTML")
    await callback.answer()


@dp.callback_query(F.data.startswith("quick_"))
async def cb_quick_range(callback: CallbackQuery):
    _, min_s, max_s = callback.data.split("_")
    min_p, max_p = float(min_s), float(max_s)
    await update_user_range(callback.from_user.id, min_p, max_p)
    settings = await get_user_settings(callback.from_user.id)

    await callback.message.edit_text(
        f"✅ <b>Фильтр обновлён!</b>\n\n"
        f"🎯 Текущий диапазон: <b>от {min_p:g} до {max_p:g} TON (Gram)</b>",
        reply_markup=build_main_menu(settings),
        parse_mode="HTML",
    )
    await callback.answer(f"Установлен диапазон {min_p:g}–{max_p:g} TON")


@dp.callback_query(F.data == "custom_price")
async def cb_custom_price(callback: CallbackQuery, state: FSMContext):
    await state.set_state(PriceFilterState.waiting_for_range)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        "✍️ <b>Введи нужный диапазон цены (От и До) через пробел или дефис.</b>\n\n"
        "Например:\n"
        "<code>12 16</code>\n"
        "или\n"
        "<code>10.5 - 25</code>",
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@dp.message(PriceFilterState.waiting_for_range)
async def process_custom_price(message: Message, state: FSMContext):
    # Ищем два числа (целых или дробных) в сообщении пользователя
    nums = re.findall(r"\d+(?:[.,]\d+)?", message.text.replace(",", "."))
    if len(nums) < 2:
        await message.answer("❌ Не понял формат. Напиши два числа через пробел, например: <code>12 16</code>",
                             parse_mode="HTML")
        return

    min_p = float(nums[0])
    max_p = float(nums[1])
    if min_p > max_p:
        min_p, max_p = max_p, min_p

    await update_user_range(message.from_user.id, min_p, max_p)
    await state.clear()
    settings = await get_user_settings(message.from_user.id)

    await message.answer(
        f"✅ <b>Диапазон успешно сохранён!</b>\n\n"
        f"🎯 Теперь ищу юзернеймы по цене: <b>от {min_p:g} до {max_p:g} TON</b>",
        reply_markup=build_main_menu(settings),
        parse_mode="HTML",
    )


@dp.callback_query(F.data == "toggle_notify")
async def cb_toggle_notify(callback: CallbackQuery):
    new_state = await toggle_user_active(callback.from_user.id)
    settings = await get_user_settings(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=build_main_menu(settings))
    await callback.answer("Уведомления включены!" if new_state else "Уведомления поставлены на паузу")


@dp.callback_query(F.data.startswith("list_page_"))
async def cb_show_list(callback: CallbackQuery):
    page = int(callback.data.split("_")[-1])
    settings = await get_user_settings(callback.from_user.id)
    min_p, max_p = settings["min_price"], settings["max_price"]

    await callback.answer("Загружаю актуальные лоты с Fragment...")

    items = await get_current_matching_items(min_p, max_p)

    if not items:
        text = (
            f"😕 <b>В диапазоне {min_p:g}–{max_p:g} TON на первых страницах сейчас ничего не найдено.</b>\n\n"
            f"Как только кто-то выставит юзернейм по такой цене, бот сразу пришлёт его в чат и добавит сюда!"
        )
    else:
        text = (
            f"📋 <b>Юзернеймы в продаже и на аукционе ({min_p:g}–{max_p:g} TON)</b>\n"
            f"Найдено подходящих лотов: <b>{len(items)} шт.</b>\n\n"
            f"<i>Нажми на любую кнопку ниже, чтобы сразу перейти к покупке на Fragment:</i>"
        )

    kb = build_items_list_kb(items, page=page)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        # Игнорируем ошибку Telegram "message is not modified" при повторном нажатии "Обновить"
        pass


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery):
    await callback.answer()


# ================= ЗАПУСК =================
async def main():
    await init_db()
    # Запускаем фоновый парсер параллельно с поллингом бота
    asyncio.create_task(monitor_worker())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())