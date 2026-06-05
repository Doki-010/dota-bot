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
HEROES_FILE = "heroes.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_cache = {}

# === ЗАГРУЗКА ГЕРОЕВ ===
def load_heroes():
    try:
        if Path(HEROES_FILE).exists():
            with open(HEROES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки heroes.json: {e}")
    return {}

heroes_db = load_heroes()
logger.info(f"✅ Загружено {len(heroes_db)} героев из {HEROES_FILE}")

def get_hero_info(hero_id):
    hero_id_str = str(hero_id)
    if hero_id_str in heroes_db:
        return heroes_db[hero_id_str]
    return {"name_ru": "Неизвестный герой", "emoji": "⚔️"}

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
    
    rank_tier = s.get("rank_tier")
    if rank_tier:
        tier = rank_tier // 10
        stars = rank_tier % 10
        medals = ["Herald", "Guardian", "Crusader", "Archon", "Legend", "Ancient", "Divine", "Immortal"]
        medal_name = medals[tier - 1] if 1 <= tier <= 8 else "Unknown"
        rank_text = f"Ранг: {medal_name} {stars}★"
    else:
        rank_text = "Ранг: Нет данных (не играл рейтинг недавно или профиль скрыт)"
    
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total = wins + losses
    wr = f"{(wins/total*100):.1f}%" if total > 0 else "0%"

    text = [
        f"🎮 <b>{name}</b>",
        f"🏆 <b>{rank_text}</b> | WR: {wr} ({total} игр)",
        "", "<b>📜 Последние 5 матчей:</b>"
    ]
    
    for m in data["matches"]:
        hero_id = m.get("hero_id", 0)
        hero_info = get_hero_info(hero_id)
        
        kda = f"{m['kills']}/{m['deaths']}/{m['assists']}"
        dur = m["duration"] // 60
        match_id = m.get("match_id", "???")
        
        # === НАДЕЖНАЯ ПРОВЕРКА ПОБЕДЫ ===
        radiant_win = m.get("radiant_win")
        player_slot = m.get("player_slot", 0)
        is_radiant = player_slot < 128
        
        # Берем значение win из API, но если его нет или оно странное, считаем сами
        api_win = m.get("win")
        if api_win is None:
            actual_win = (radiant_win == is_radiant)
            logger.info(f"Матч {match_id}: поле win отсутствовало, рассчитано как {actual_win}")
        else:
            actual_win = bool(api_win)
            
        win_emoji = "✅" if actual_win else "❌"
        # ==================================
        
        text.append(f"{win_emoji} {hero_info['emoji']} {hero_info['name_ru']} | {kda} | {dur}м")
        
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
    
    logger.info("✅ Бот запущен с отдельной базой героев!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
