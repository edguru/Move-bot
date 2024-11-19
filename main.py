import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from misc import broadcast_notifications, resolve_bets, convert_to_timezone
from db import Database

# Bot and DB setup
BOT_TOKEN = "YOUR_BOT_TOKEN"
MONGO_URI = "YOUR_MONGO_URI"
DB_NAME = "YOUR_DB_NAME"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
db = Database(MONGO_URI, DB_NAME)
scheduler = AsyncIOScheduler()

# Commands

@dp.message_handler(commands=["start"])
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    await db.create_user(user_id)  # Ensure user exists
    buttons = InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("Predict", callback_data="predict"),
        InlineKeyboardButton("Refer", callback_data="refer"),
        InlineKeyboardButton("Create a Prediction", callback_data="create_prediction"),
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

# Run Bot
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
