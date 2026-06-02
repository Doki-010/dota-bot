import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiohttp import ClientSession

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Переменная BOT_TOKEN не найдена!")

CACHE_TTL = 300  # Кэш на 5 минут
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_cache = {}

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

async def cmd_profile(message: types.Message):
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        return await message.answer("❗ Формат: /profile 87276347", parse_mode="HTML")
    
    wait_msg = await message.answer("⏳ Ищу игрока...")
    data = await get_player_data(args[1])
    
    if not data:
        return await wait_msg.edit_text("❌ Игрок не найден")
    
    await wait_msg.edit_text(format_profile(data), parse_mode="HTML")

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.message.register(cmd_profile, Command("profile"))
    logger.info("✅ Бот успешно запущен на сервере!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
