# 🎨 ImageBot

Лёгкий Telegram-бот для генерации картинок через GPT Image (или совместимую модель) — по тексту, по фото, по нескольким фото. Whitelist-доступ, дневные лимиты, переключаемые провайдеры.

## 🗂️ Структура

```
src/
  core/
    config.py          # Pydantic Settings — все параметры из .env
    db.py               # aiosqlite singleton, схема применяется на старте
    router_manager.py   # сборка роутеров
  db/
    schema.sql           # users, daily_usage, generations, transactions, settings
  providers/
    base.py               # ImageProvider Protocol
    openai_compat.py       # любой OpenAI-совместимый агрегатор (ProxyAPI и т.д.)
    gen_api.py              # нативный Gen-API (submit + poll)
    registry.py              # выбор провайдера по PROVIDER_TYPE
  services/
    user.py               # whitelist CRUD
    quota.py                # дневные лимиты
    settings.py              # настройки из БД (модель, размер, качество)
    image_gen.py              # единая точка входа для генерации
  handlers/
    start.py               # /start, /help, кнопки меню
    generate.py              # FSM-флоу генерации (текст / фото / мульти-фото)
    admin.py                   # управление пользователями и настройками
  middlewares/
    auth.py                 # проверка whitelist из БД
    logger.py                 # лог апдейтов
  keyboards/
    gen.py                   # inline + reply клавиатуры
  states/
    generate.py               # FSM States
  main.py
```

## ⚡ Стек

| Компонент | Технология |
|---|---|
| Фреймворк | Aiogram 3 |
| БД | SQLite (aiosqlite) |
| FSM storage | Redis |
| Провайдер | OpenAI-совместимый агрегатор или Gen-API |
| Конфиг | Pydantic Settings |
| Логи | Loguru |
| Контейнеры | Docker + docker-compose |

## 🚀 Быстрый старт

```bash
git clone <repo>
cd imagebot

cp .env.example .env
# заполни BOT_TOKEN, ADMIN_IDS, PROVIDER_API_KEY (см. ниже)

docker compose up --build -d
```

Бот сам создаст `data/bot.db` со схемой и подключится к Redis при старте.

### Локально без Docker

```bash
pip install -r requirements.txt

# Redis должен быть доступен — либо локально, либо через docker:
docker run -d -p 6379:6379 redis:7-alpine
# тогда в .env: REDIS_HOST=localhost

python -m src.main
```

## 🔧 .env

```env
BOT_TOKEN=your_telegram_bot_token
ADMIN_IDS=[123456789]

# Провайдер: openai_compat | genapi
PROVIDER_TYPE=openai_compat

# Используется если PROVIDER_TYPE=openai_compat
PROVIDER_BASE_URL=https://api.proxyapi.ru/openai/v1
PROVIDER_API_KEY=your_aggregator_key

# Используется если PROVIDER_TYPE=genapi
GENAPI_BASE_URL=https://api.gen-api.ru
GENAPI_API_KEY=your_genapi_key

# Модель по умолчанию (переопределяется через /setmodel, хранится в БД)
DEFAULT_IMAGE_MODEL=gpt-image-1

# Параметры генерации по умолчанию (переопределяются через /setquality, хранятся в БД)
IMAGE_SIZE=1024x1024
IMAGE_QUALITY=medium

# Максимум фото в режиме "несколько фото"
MAX_MULTI_IMAGES=3

# Лимит генераций в день (per-user лимит можно задать отдельно через /setlimit)
DEFAULT_DAILY_LIMIT=10

# Redis (FSM storage — обязателен)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

LOG_LEVEL=INFO
```

## 🔌 Провайдеры

### openai_compat (по умолчанию)
Работает с любым OpenAI-совместимым API: ProxyAPI, OpenRouter, напрямую OpenAI. Достаточно поменять `PROVIDER_BASE_URL` и `PROVIDER_API_KEY`.

**Важно про мульти-фото:** большинство агрегаторов (включая ProxyAPI) принимают только один файл в `images/edits`, даже если документация OpenAI заявляет поддержку нескольких. Поэтому при загрузке нескольких фото бот склеивает их в одно изображение горизонтальной полосой перед отправкой — это работает надёжно на любом агрегаторе.

### genapi
Нативная интеграция с [Gen-API](https://gen-api.ru) — асинхронная схема: отправка задачи → поллинг статуса → скачивание результата. Поддерживает реальную отправку нескольких изображений в одном запросе (`images: [...]` в payload), без склейки.

Чтобы переключиться, в `.env`:
```env
PROVIDER_TYPE=genapi
GENAPI_API_KEY=...
```

Перед продакшен-использованием сверь точные названия полей запроса/ответа с актуальной документацией Gen-API — она может отличаться от заложенной в `gen_api.py` схемы.

### Добавить свой провайдер
1. Создай `src/providers/your_provider.py`, реализуй `generate()` и `edit()` по протоколу `ImageProvider` (см. `base.py`)
2. Подключи в `providers/registry.py` по новому значению `PROVIDER_TYPE`

## 🤖 Команды

### Пользовательские
| Команда | Действие |
|---|---|
| `/start` | приветствие, показывает лимит на сегодня |
| `/help` | помощь |
| `/gen`, `/generate`, `/g` | запустить генерацию (то же что кнопка 🎨) |
| `/cancel` | отменить текущий шаг генерации |

Также доступны через reply-клавиатуру: **🎨 Сгенерировать**, **📊 Остаток**, **❓ Помощь**.

### Админские (только для `ADMIN_IDS`)
| Команда | Действие |
|---|---|
| `/admin` | список всех админ-команд |
| `/adduser <user_id> [limit]` | добавить пользователя в whitelist |
| `/removeuser <user_id>` | деактивировать пользователя |
| `/setlimit <user_id> <limit>` | задать персональный дневной лимит |
| `/users` | список активных пользователей с их usage |
| `/setmodel <model>` | сменить модель генерации (хранится в БД, без рестарта) |
| `/setquality <low\|medium\|high>` | сменить качество генерации |
| `/model` | показать текущую модель/размер/качество |

## 🔐 Доступ и лимиты

- Whitelist хранится в таблице `users`, не в `.env` — управляется командами на лету
- Каждый пользователь имеет `daily_limit` (по умолчанию `DEFAULT_DAILY_LIMIT`, переопределяется через `/setlimit`)
- Счётчик использования — таблица `daily_usage`, сбрасывается автоматически по дате (без крона)
- Админы из `ADMIN_IDS` не ограничены лимитом

## 💳 Оплата (заложено, не активировано)

В схеме уже есть `balance` у пользователя и таблица `transactions` — когда понадобится монетизация, логику списания/пополнения можно добавить без миграции схемы.

## 🗄️ Данные

SQLite-файл лежит в `data/bot.db`, монтируется как volume в Docker — переживает рестарт контейнера. Бэкап — просто скопировать файл.

```bash
# бэкап
cp data/bot.db data/bot.db.bak

# посмотреть всех юзеров
sqlite3 data/bot.db "SELECT * FROM users;"
```

## 🛠️ Локальная разработка

```bash
# логи в реальном времени
docker compose logs -f bot

# зайти в контейнер
docker compose exec bot bash

# рестарт после изменений в .env
docker compose up -d --force-recreate bot
```
