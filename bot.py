import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import ClientSession

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Переменная BOT_TOKEN не найдена!")

CACHE_TTL = 300
DB_FILE = "users.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_cache = {}

# === БАЗА ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ===
def load_users():
    if Path(DB_FILE).exists():
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_users(users):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

users_db = load_users()

# === API OPENDOTA ===
async def fetch_json(session, url):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        logger.error(f"API Error: {e}")
    return None

async def get_player_data(account_id):
    now = datetime.now().timestamp()
    cached = _cache.get(account_id)
    if cached and (now - cached["ts"]) < CACHE_TTL:
        return cached["data"]

    async with ClientSession() as session:
        profile_url = f"https://api.opendota.com/api/players/{account_id}"
        matches_url = f"https://api.opendota.com/api/players/{account_id}/recentMatches?limit=5"
        profile, matches = await asyncio.gather(
            fetch_json(session, profile_url),
            fetch_json(session, matches_url)
        )

    if not profile or not profile.get("profile"):
        return None

    data = {"profile": profile, "matches": matches or []}
    _cache[account_id] = {"data": data, "ts": now}
    return data

# === ФОРМАТИРОВАНИЕ ===
def format_profile(data):
    p = data["profile"]["profile"]
    s = data["profile"]
    name = p.get("personaname", "Unknown")
    mmr = s.get("mmr_estimate", {}).get("estimate", "Скрыт")
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total = wins + losses
    wr = f"{(wins/total*100):.1f}%" if total > 0 else "0%"

    text = [
        f"🎮 <b>{name}</b>",
        f"🏆 MMR: <b>{mmr}</b> | WR: {wr} ({total} игр)",
        "", "<b>📜 Последние 5 матчей:</b>"
    ]
    for m in data["matches"]:
        hero = m.get("hero_name", "?")
        kda = f"{m['kills']}/{m['deaths']}/{m['assists']}"
        dur = m["duration"] // 60
        win = "✅" if m.get("win") else "❌"
        text.append(f"{win} {hero} | {kda} | {dur}м")
    if not data["matches"]:
        text.append("Нет недавних матчей")
    return "\n".join(text)

# === КОМАНДЫ ===
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    linked = users_db.get(user_id)
    
    text = (
        "👋 <b>Привет! Я Dota 2 Stats Bot</b>\n\n"
        "Я показываю статистику игроков и последние матчи.\n\n"
        "<b>Команды:</b>\n"
        "/link &lt;ID&gt; — привязать свой аккаунт\n"
        "/profile [ID] — посмотреть статистику\n"
        "/unlink — отвязать аккаунт\n\n"
        "<i>Найти свой ID можно на opendota.com</i>"
    )
    if linked:
        text += f"\n\n✅ Твой привязанный ID: <code>{linked}</code>"
    
    await message.answer(text, parse_mode="HTML")

async def cmd_link(message: types.Message):
    args = message.text.split()
    user_id = str(message.from_user.id)
    
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer(
            "❗ Формат: <code>/link 87276347</code>\n"
            "Найти ID: opendota.com → поиск по нику → URL",
            parse_mode="HTML"
        )
    
    account_id = args[1]
    # Проверяем, существует ли аккаунт
    data = await get_player_data(account_id)
    if not data:
        return await message.answer("❌ Аккаунт не найден или приватен. Проверь ID.")
    
    users_db[user_id] = account_id
    save_users(users_db)
    
    name = data["profile"]["profile"].get("personaname", "Unknown")
    await message.answer(
        f"✅ Аккаунт <b>{name}</b> (<code>{account_id}</code>) успешно привязан!\n"
        "Теперь используй просто /profile",
        parse_mode="HTML"
    )

async def cmd_unlink(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in users_db:
        del users_db[user_id]
        save_users(users_db)
        await message.answer("🗑 Аккаунт отвязан.")
    else:
        await message.answer("У тебя нет привязанного аккаунта.")

async def cmd_profile(message: types.Message):
    args = message.text.split()
    user_id = str(message.from_user.id)
    
    # Определяем какой ID использовать
    if len(args) >= 2 and args[1].isdigit():
        account_id = args[1]
    elif user_id in users_db:
        account_id = users_db[user_id]
    else:
        return await message.answer(
            "❗ Укажи ID: <code>/profile 87276347</code>\n"
            "Или привяжи аккаунт через /link",
            parse_mode="HTML"
        )
    
    wait_msg = await message.answer("⏳ Ищу игрока...")
    data = await get_player_data(account_id)
    
    if not data:
        return await wait_msg.edit_text("❌ Игрок не найден или профиль приватен")
    
    await wait_msg.edit_text(format_profile(data), parse_mode="HTML")

# === ЗАПУСК ===
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_link, Command("link"))
    dp.message.register(cmd_unlink, Command("unlink"))
    dp.message.register(cmd_profile, Command("profile"))
    
    logger.info("✅ Бот запущен с системой регистрации!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
