import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from misc import broadcast_notifications, resolve_bets, convert_to_timezone
from db import Database
from dotenv import load_dotenv
import os
from functools import wraps
from aiogram.exceptions import TelegramBadRequest
import logging

# Load environment variables
load_dotenv()

# Bot and DB setup
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID"))

# Optional configurations
MAX_BET = int(os.getenv("MAX_BET_AMOUNT", 100))
MIN_BET = int(os.getenv("MIN_BET_AMOUNT", 10))

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
db = Database(MONGO_URI, DB_NAME)
scheduler = AsyncIOScheduler()

# Decorator for admin-only commands
def admin_required(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = message.from_user.id
        if not (await db.is_admin(user_id) or await db.is_bot_owner(user_id)):
            await message.reply("⛔️ This command is only available to administrators.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

# Decorator for bot owner only commands
def owner_required(func):
    @wraps(func)
    async def wrapper(message: types.Message, *args, **kwargs):
        user_id = message.from_user.id
        if not await db.is_bot_owner(user_id):
            await message.reply("⛔️ This command is only available to the bot owner.")
            return
        return await func(message, *args, **kwargs)
    return wrapper

# Commands
@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    await db.create_user(user_id)  # Ensure user exists
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Predict", callback_data="predict"),
            InlineKeyboardButton(text="Refer", callback_data="refer")
        ],
        [
            InlineKeyboardButton(text="Create a Prediction", callback_data="create_prediction"),
            InlineKeyboardButton(text="Help", callback_data="help")
        ]
    ])
    await message.answer("Welcome to the Prediction Bot! Choose an option:", reply_markup=buttons)

@dp.message(Command("addwallet"))
async def add_wallet_handler(message: types.Message):
    await message.answer("Please send your wallet address.")

@dp.message(Command("balance"))
async def balance_handler(message: types.Message):
    user_id = message.from_user.id
    balance = await db.get_user_balance(user_id)
    points = await db.get_user_points(user_id)
    await message.answer(f"Your balance:\nTokens: {balance}\nPoints: {points}")

# ... (continue updating other handlers) ...

async def main():
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Start scheduler
    scheduler.add_job(automatic_resolution, "interval", hours=1)
    scheduler.start()
    
    # Start bot
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())


