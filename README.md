# blrd ai

Коммерческий Telegram бот и веб-приложение для работы с множеством AI моделей через AnyModel.

**Функции:**
- Чат с выбором модели (DeepSeek, GPT, Claude, Gemini и др.)
- Веб-приложение (Mini App) с историей чатов
- Загрузка изображений и документов (PDF, DOCX, TXT)
- Подписка Pro через Platega
- Промокоды и рассылки
- Админ-панель: статистика, управление пользователями, конфиги моделей

**Стэк:** FastAPI, aiogram 3, SQLAlchemy, PostgreSQL, Telegram Bot API, AnyModel API

---

## Быстрый старт (локально, PyCharm)

### 1. Требования
- Python 3.11+
- PostgreSQL или SQLite (по умолчанию SQLite для разработки)

### 2. Клон и окружение
```bash
git clone https://github.com/YOUR_ORG/blrdai.git
cd blrdai
python -m venv .venv
.venv\Scripts\activate  # Windows
# или: source .venv/bin/activate  # Linux/macOS

pip install -r requirements.txt
