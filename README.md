```markdown
# 🎨 ImageBot

Лёгкий Telegram-бот для генерации картинок через GPT Image (или совместимую модель) — по тексту, по фото, по нескольким фото. Whitelist-доступ, дневные лимиты, переключаемые провайдеры, управление через инлайн-админку.

## 🗂️ Структура

```
src/
  core/
    config.py          # Pydantic Settings — все параметры из .env
    db.py               # aiosqlite singleton, схема применяется на старте
    router_manager.py   # сборка роутеров
  db/
    schema.sql           # users, daily_usage, generations, transactions, settings
  filters/
    check_admin.py        # фильтр IsAdmin по ADMIN_IDS
  providers/
    base.py               # ImageProvider Protocol
    openai_compat.py       # любой OpenAI-совместимый агрегатор (AITunnel, ProxyAPI и т.д.)
    gen_api.py              # нативный Gen-API (submit + poll)
  services/
    user.py               # whitelist CRUD
    quota.py                # дневные лимиты, атомарное резервирование
    settings.py              # настройки из БД (модель, размер, качество)
    image_gen.py              # единая точка входа для генерации, round-robin + fallback
  handlers/
    start.py               # /start, /help, кнопки меню
    generate.py              # FSM-флоу генерации (текст / фото / мульти-фото)
    admin.py                   # инлайн-админка + текстовые команды управления
  middlewares/
    auth.py                 # whitelist из БД (авторегистрация новых юзеров)
    logger.py                 # лог апдейтов (с обрезкой длинных промптов)
    throttle.py                # антифлуд in-memory
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
# заполни BOT_TOKEN, ADMIN_IDS, и ключ хотя бы одного провайдера (см. ниже)

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

# Провайдер: openai_compat | genapi (переопределяется на лету из админки/через /setprovider)
PROVIDER_TYPE=openai_compat

# OpenAI-совместимый агрегатор (AITunnel, ProxyAPI, OpenRouter и т.д.)
PROVIDER_BASE_URL=https://api.aitunnel.ru/v1
PROVIDER_API_KEY=your_aggregator_key

# Gen-API нативный провайдер
GENAPI_BASE_URL=https://api.gen-api.ru
GENAPI_API_KEY=your_genapi_key

# Модель по умолчанию (переопределяется из инлайн-админки, хранится в БД)
DEFAULT_IMAGE_MODEL=gpt-image-2

# Параметры генерации по умолчанию
IMAGE_SIZE=1024x1024
IMAGE_QUALITY=low   # качество жёстко зафиксировано на "low" в коде (см. ниже), это значение сейчас не влияет на рантайм

# Максимум фото в режиме "несколько фото"
MAX_MULTI_IMAGES=3

# Лимит генераций в день по умолчанию (per-user лимит задаётся отдельно через /setlimit)
DEFAULT_DAILY_LIMIT=10

# Redis (FSM storage — обязателен)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

LOG_LEVEL=INFO
```

Оба провайдера могут быть настроены одновременно (заполнены оба ключа) — тогда бот балансирует между ними round-robin и делает fallback при ошибке одного из них.

## 🔌 Провайдеры

### openai_compat
Работает с любым OpenAI-совместимым API: AITunnel, ProxyAPI, OpenRouter, напрямую OpenAI. Достаточно поменять `PROVIDER_BASE_URL` и `PROVIDER_API_KEY`. Поддерживает как генерацию по тексту, так и по фото (`edit`).

**Про мульти-фото:** большинство агрегаторов принимают только один файл в `images/edits`, даже если документация OpenAI заявляет поддержку нескольких. Поэтому при загрузке нескольких фото бот склеивает их в одно изображение горизонтальной полосой перед отправкой — это работает надёжно на любом агрегаторе. Это поведение единое для обоих провайдеров (`openai_compat` и `genapi`).

### genapi
Нативная интеграция с Gen-API (submit → poll → download). Генерация по фото (`edit`) технически ограничена — Gen-API не принимает файлы через API корректно во всех случаях, поэтому **этот провайдер сейчас исключается из пула для запросов с фото** (`supports_edits: False` в `image_gen.py`), и используется только для генерации по тексту. Если нужна генерация по фото — используй `openai_compat` (AITunnel).

Перед продакшен-использованием сверь точные названия полей запроса/ответа с актуальной документацией Gen-API — она может отличаться от заложенной в `gen_api.py` схемы.

### Сопоставление моделей (Model Mapping)
Абстрактные ключи модели (`gpt-image-2`, `flux`, `midjourney`, `sd3`) транслируются в точные имена моделей каждого провайдера через `MODEL_MAPS` в `image_gen.py`. При смене активной модели через админку выбор идёт именно из этого набора ключей — см. кнопки в `admin_model_choice()`.

### Добавить свой провайдер
1. Создай `src/providers/your_provider.py`, реализуй `generate()` и `edit()` по протоколу `ImageProvider` (см. `base.py`)
2. Подключи инициализацию в пуле провайдеров (`PROVIDER_POOL`) в `src/services/image_gen.py`
3. При необходимости добавь маппинг модели в `MODEL_MAPS`

## 🤖 Команды и админка

### Пользовательские
| Команда | Действие |
|---|---|
| `/start` | приветствие, показывает лимит на сегодня |
| `/help` | помощь |
| `/gen`, `/generate`, `/g` | запустить генерацию (то же что кнопка 🎨) |
| `/cancel` | отменить текущий шаг генерации |

Также доступны через reply-клавиатуру: **🎨 Сгенерировать**, **📊 Остаток**, **❓ Помощь**.

### Админские (только для `ADMIN_IDS`)

Основной способ управления — инлайн-панель:

```
/admin
```

Открывает клавиатуру с разделами:
- **👥 Пользователи** — список активных пользователей с их usage за сегодня
- **⚙️ Настройки ИИ** — выбор активной модели и провайдера (кнопками), качество зафиксировано на Low и не редактируется из UI

Текстовые команды (используются реже, для быстрых точечных действий без захода в панель):

| Команда | Действие |
|---|---|
| `/adduser <user_id> [limit]` | добавить пользователя в whitelist |
| `/removeuser <user_id>` | деактивировать пользователя |
| `/setlimit <user_id> <limit>` | задать персональный дневной лимит |
| `/setprovider <genapi\|aitunnel\|auto>` | зафиксировать предпочитаемый провайдер (то же самое можно сделать кнопками в `/admin` → ⚙️ Настройки ИИ) |

Выбор модели делается только через инлайн-панель (`/admin` → ⚙️ Настройки ИИ → 🤖 Модель), отдельной текстовой команды для этого нет.

## 🔐 Доступ и лимиты

- Whitelist хранится в таблице `users`, не в `.env` — управляется командами/админкой на лету
- Новые пользователи (не из `ADMIN_IDS`) автоматически регистрируются при первом обращении с лимитом **1 генерация/день** (см. `WhitelistMiddleware`), дальше лимит можно поднять через `/setlimit`
- Деактивированные пользователи (`is_active = 0`) получают отказ на любое взаимодействие
- Счётчик использования — таблица `daily_usage`, сбрасывается автоматически по дате (без крона)
- Резервирование слота атомарно (`UPDATE ... WHERE count < limit`), откатывается (`release_quota`), если генерация в итоге не удалась на всех провайдерах
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

# посмотреть текущие настройки (модель, провайдер и т.д.)
sqlite3 data/bot.db "SELECT * FROM settings;"
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

## ⚠️ Известные ограничения

- Генерация по фото на `genapi` отключена в пуле (см. раздел «Провайдеры» выше) — используется только `openai_compat`
- Качество генерации жёстко зафиксировано на `low` в `services/settings.py` (защита от случайных дорогих запросов) — значение `IMAGE_QUALITY` из `.env`/БД сейчас игнорируется в рантайме
- При выборе конкретного провайдера через `/setprovider`/админку fallback на другой провайдер при ошибке не срабатывает — retry идёт на том же провайдере
```
