import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from misc import broadcast_notifications, resolve_bets, convert_to_timezone
from db import Database
from dotenv import load_dotenv
import os
from functools import wraps
from aiogram.utils.exceptions import ChatNotFound
from aiogram.contrib.middlewares.logging import LoggingMiddleware
import logging

# Load environment variables
load_dotenv()

# Bot and DB setup
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
db = Database(MONGO_URI, DB_NAME)
scheduler = AsyncIOScheduler()

# Optional configurations
MAX_BET = int(os.getenv("MAX_BET_AMOUNT", 100))
MIN_BET = int(os.getenv("MIN_BET_AMOUNT", 10))

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

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    await db.create_user(user_id)  # Ensure user exists
    buttons = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("Predict", callback_data="predict"),
        InlineKeyboardButton("Refer", callback_data="refer"),
        InlineKeyboardButton("Create a Prediction", callback_data="create_prediction"),
        InlineKeyboardButton("Help", callback_data="help")
    )
    await message.answer("Welcome to the Prediction Bot! Choose an option:", reply_markup=buttons)

@dp.message_handler(commands=["addwallet"])
async def add_wallet_handler(message: types.Message):
    await message.answer("Please send your wallet address.")
    dp.register_message_handler(wallet_address_handler, state="awaiting_wallet_address")

async def wallet_address_handler(message: types.Message):
    wallet_address = message.text
    user_id = message.from_user.id
    await db.update_user_wallet(user_id, wallet_address)
    await message.answer("Wallet address saved successfully.")
    dp.reset_state(user_id)  # Clear state

@dp.message_handler(commands=["balance"])
async def balance_handler(message: types.Message):
    user_id = message.from_user.id
    balance = await db.get_user_balance(user_id)
    points = await db.get_user_points(user_id)
    await message.answer(f"Your balance:\nTokens: {balance}\nPoints: {points}")

@dp.message_handler(commands=["predict"])
async def predict_handler(message: types.Message):
    user_id = message.from_user.id
    predictions = await db.get_active_predictions()
    if not predictions:
        await message.answer("No active predictions available.")
        return
    
    for prediction in predictions:
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("Yes", callback_data=f"bet_yes_{prediction['_id']}"),
            InlineKeyboardButton("No", callback_data=f"bet_no_{prediction['_id']}"),
        )
        await message.answer(
            f"Prediction: {prediction['question']}\nBids close: {convert_to_timezone(prediction['expiry_time'], 'UTC')}",
            reply_markup=keyboard,
        )

@dp.message_handler(commands=["create"])
async def create_handler(message: types.Message):
    user_id = message.from_user.id
    if not await db.is_kol(user_id):
        await message.reply("⛔️ Only KOLs can create predictions.")
        return
    
    await message.answer("Please send your prediction question.")
    dp.register_message_handler(prediction_question_handler, state="awaiting_prediction_question")

async def prediction_question_handler(message: types.Message):
    question = message.text
    user_id = message.from_user.id
    await db.add_prediction_draft(user_id, question)
    await message.answer("Prediction saved. Please specify the deadline (YYYY-MM-DD HH:MM format).")
    dp.register_message_handler(prediction_deadline_handler, state="awaiting_deadline")

async def prediction_deadline_handler(message: types.Message):
    user_id = message.from_user.id
    try:
        deadline = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
        await db.finalize_prediction(user_id, deadline)
        await message.answer("Prediction created successfully.")
    except ValueError:
        await message.answer("Invalid date format. Please use YYYY-MM-DD HH:MM.")

@dp.message_handler(commands=["resolve"])
async def resolve_handler(message: types.Message):
    user_id = message.from_user.id
    predictions = await db.get_user_predictions(user_id, active_only=True)
    if not predictions:
        await message.answer("No active predictions to resolve.")
        return
    
    for prediction in predictions:
        keyboard = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("Yes", callback_data=f"resolve_yes_{prediction['_id']}"),
            InlineKeyboardButton("No", callback_data=f"resolve_no_{prediction['_id']}"),
        )
        await message.answer(f"Resolve Prediction: {prediction['question']}", reply_markup=keyboard)

@dp.message_handler(commands=["addkol"])
@admin_required
async def add_kol_handler(message: types.Message):
    # Check if message is a reply or contains a user ID
    try:
        if message.reply_to_message:
            user_id = message.reply_to_message.from_user.id
            username = message.reply_to_message.from_user.username
        else:
            args = message.get_args().split()
            if not args:
                await message.reply("Please reply to a user's message or provide a user ID.")
                return
            user_id = int(args[0])
            user = await bot.get_chat(user_id)
            username = user.username
        
        # Add user as KOL
        if await db.add_kol(user_id):
            await message.reply(f"✅ Successfully added @{username} (ID: {user_id}) as a KOL.")
        else:
            await message.reply("❌ Failed to add KOL. User might already be a KOL.")
    
    except (ValueError, ChatNotFound):
        await message.reply("❌ Invalid user ID or user not found.")
    except Exception as e:
        await message.reply(f"❌ An error occurred: {str(e)}")

@dp.message_handler(commands=["addadmin"])
@owner_required
async def add_admin_handler(message: types.Message):
    try:
        if message.reply_to_message:
            user_id = message.reply_to_message.from_user.id
            username = message.reply_to_message.from_user.username
        else:
            args = message.get_args().split()
            if not args:
                await message.reply("Please reply to a user's message or provide a user ID.")
                return
            user_id = int(args[0])
            user = await bot.get_chat(user_id)
            username = user.username
        
        # Add user as admin
        if await db.add_admin(user_id):
            await message.reply(f"✅ Successfully added @{username} (ID: {user_id}) as an admin.")
        else:
            await message.reply("❌ Failed to add admin. User might already be an admin.")
    
    except (ValueError, ChatNotFound):
        await message.reply("❌ Invalid user ID or user not found.")
    except Exception as e:
        await message.reply(f"❌ An error occurred: {str(e)}")

@dp.message_handler(commands=["help"])
async def help_handler(message: types.Message):
    help_text = """
🤖 *Available Commands:*

/start - Start the bot and see main menu
/help - Show this help message
/predict - View and bet on active predictions
/create - Create a new prediction
/balance - Check your token and points balance
/addwallet - Add your wallet address
/resolve - Resolve your created predictions

*How to use:*
1. Use /predict to view active predictions
2. Place bets using the buttons (min: {min_bet}, max: {max_bet} tokens)
3. Create your own predictions using /create
4. Check your earnings with /balance

*Need more help?*
Contact support: @your_support_username
    """.format(min_bet=MIN_BET, max_bet=MAX_BET)

    await message.answer(help_text, parse_mode="Markdown")

# Callback Handlers

@dp.callback_query_handler(lambda c: c.data.startswith("bet"))
async def bet_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    prediction_id, choice = data[2], data[1]
    
    await callback_query.message.answer("Choose your bet amount (10 to 100):")
    dp.register_message_handler(
        lambda msg: bet_amount_handler(msg, user_id, prediction_id, choice),
        state="awaiting_bet_amount",
    )

async def bet_amount_handler(message: types.Message, user_id, prediction_id, choice):
    try:
        amount = int(message.text)
        if amount < 10 or amount > 100:
            raise ValueError
        await db.place_bet(user_id, prediction_id, choice, amount)
        await message.answer(f"Bet placed successfully! You bet {amount} tokens on {choice.upper()}.")
    except ValueError:
        await message.answer("Invalid amount. Please enter a value between 10 and 100.")

@dp.callback_query_handler(lambda c: c.data.startswith("resolve"))
async def resolve_prediction_handler(callback_query: types.CallbackQuery):
    data = callback_query.data.split("_")
    prediction_id, result = data[2], data[1]
    user_id = callback_query.from_user.id
    await db.resolve_prediction(user_id, prediction_id, result)
    await callback_query.message.answer(f"Prediction resolved as '{result.upper()}'. Rewards distributed.")

# Automatic Resolution with Scheduler

async def automatic_resolution():
    while True:
        await resolve_bets(bot, db)
        await asyncio.sleep(3600)  # Run every hour

# Scheduler setup
scheduler.add_job(automatic_resolution, "interval", hours=1)
scheduler.start()

# Add callback handler for help button
@dp.callback_query_handler(lambda c: c.data == "help")
async def help_button_handler(callback_query: types.CallbackQuery):
    await help_handler(callback_query.message)
    await callback_query.answer()

# Configure logging
logging.basicConfig(level=logging.INFO)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)


