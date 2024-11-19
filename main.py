import asyncio
from aiogram import Bot, Dispatcher, types, F, html
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
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

# Define states
class PredictionStates(StatesGroup):
    awaiting_wallet_address = State()
    awaiting_prediction_question = State()
    awaiting_deadline = State()
    awaiting_bet_amount = State()
    awaiting_kol_id = State()
    awaiting_admin_id = State()

# Add callback query handlers
@dp.callback_query(lambda c: c.data == "help")
async def help_button_handler(callback_query: types.CallbackQuery):
    await help_handler(callback_query.message)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "predict")
async def predict_button_handler(callback_query: types.CallbackQuery):
    # Add your prediction handling logic here
    await callback_query.answer("Prediction feature coming soon!")

@dp.callback_query(lambda c: c.data == "refer")
async def refer_button_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    ref_info = await db.get_referral_info(user_id)
    
    text = f"""
📊 *Your Referral Stats*
Total Referrals: {ref_info['count']}
Points Earned: {ref_info['points']}

🔗 *Your Referral Link*
{ref_info['referral_link']}

Share this link with friends to earn points!
"""
    await callback_query.message.answer(text, parse_mode="Markdown")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "create_prediction")
async def create_prediction_button_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if not await db.is_kol(user_id):
        await callback_query.answer("Only KOLs can create predictions!", show_alert=True)
        return
    await callback_query.message.answer("Please send your prediction question.")
    await callback_query.answer()

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

@dp.message(Command("help"))
async def help_handler(message: types.Message):
    user_id = message.from_user.id
    is_admin = await db.is_admin(user_id)
    is_owner = await db.is_bot_owner(user_id)
    is_kol = await db.is_kol(user_id)

    help_text = """
🤖 *Available Commands:*

/start - Start the bot and see main menu
/help - Show this help message
/predict - View and bet on active predictions
/balance - Check your token and points balance
/addwallet - Add your wallet address
"""

    if is_kol:
        help_text += """
*KOL Commands:*
/create - Create a new prediction
/resolve - Resolve your created predictions
"""

    if is_admin:
        help_text += """
*Admin Commands:*
/addkol - Add a new KOL (Reply to message or use user ID)
"""

    if is_owner:
        help_text += """
*Owner Commands:*
/addadmin - Add a new admin (Reply to message or use user ID)
"""

    help_text += f"""
*How to use:*
1. Use /predict to view active predictions
2. Place bets using the buttons (min: {MIN_BET}, max: {MAX_BET} tokens)
3. Check your earnings with /balance

*Need more help?*
Contact support: @your_support_username
"""

    await message.answer(help_text, parse_mode="Markdown")

@dp.message(Command("addwallet"))
async def add_wallet_handler(message: types.Message, state: FSMContext):
    await state.set_state(PredictionStates.awaiting_wallet_address)
    await message.answer("Please send your wallet address.")

@dp.message(Command("balance"))
async def balance_handler(message: types.Message):
    user_id = message.from_user.id
    balance = await db.get_user_balance(user_id)
    points = await db.get_user_points(user_id)
    await message.answer(f"Your balance:\nTokens: {balance}\nPoints: {points}")

# Automatic resolution function
async def automatic_resolution():
    await resolve_bets(bot, db)

# Add prediction handlers
@dp.message(Command("predict"))
async def predict_handler(message: types.Message):
    user_id = message.from_user.id
    predictions = await db.get_active_predictions()
    if not predictions:
        await message.answer("No active predictions available.")
        return
    
    for prediction in predictions:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Yes", callback_data=f"bet_yes_{prediction['_id']}"),
                InlineKeyboardButton(text="No", callback_data=f"bet_no_{prediction['_id']}")
            ]
        ])
        await message.answer(
            f"Prediction: {prediction['question']}\n"
            f"Bids close: {convert_to_timezone(prediction['expiry_time'], 'UTC')}",
            reply_markup=keyboard
        )

@dp.message(Command("create"))
async def create_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if not await db.is_kol(user_id):
        await message.reply("⛔️ Only KOLs can create predictions.")
        return
    
    await state.set_state(PredictionStates.awaiting_prediction_question)
    await message.answer("Please send your prediction question.")

@dp.message(PredictionStates.awaiting_prediction_question)
async def prediction_question_handler(message: types.Message, state: FSMContext):
    question = message.text
    user_id = message.from_user.id
    await db.add_prediction_draft(user_id, question)
    await state.set_state(PredictionStates.awaiting_deadline)
    await message.answer("Prediction saved. Please specify the deadline (YYYY-MM-DD HH:MM format).")

@dp.message(PredictionStates.awaiting_deadline)
async def prediction_deadline_handler(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        deadline = datetime.strptime(message.text, "%Y-%m-%d %H:%M")
        await db.finalize_prediction(user_id, deadline)
        await message.answer("Prediction created successfully.")
        await state.clear()
    except ValueError:
        await message.answer("Invalid date format. Please use YYYY-MM-DD HH:MM.")

@dp.message(Command("resolve"))
async def resolve_handler(message: types.Message):
    user_id = message.from_user.id
    predictions = await db.get_user_predictions(user_id, active_only=True)
    if not predictions:
        await message.answer("No active predictions to resolve.")
        return
    
    for prediction in predictions:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="Yes", callback_data=f"resolve_yes_{prediction['_id']}"),
                InlineKeyboardButton(text="No", callback_data=f"resolve_no_{prediction['_id']}")
            ]
        ])
        await message.answer(f"Resolve Prediction: {prediction['question']}", reply_markup=keyboard)

# Callback handlers
@dp.callback_query(F.data.startswith("bet_"))
async def bet_handler(callback_query: types.CallbackQuery, state: FSMContext):
    user_id = callback_query.from_user.id
    data = callback_query.data.split("_")
    prediction_id, choice = data[2], data[1]
    
    await state.update_data(prediction_id=prediction_id, choice=choice)
    await state.set_state(PredictionStates.awaiting_bet_amount)
    await callback_query.message.answer("Choose your bet amount (10 to 100):")
    await callback_query.answer()

@dp.message(PredictionStates.awaiting_bet_amount)
async def bet_amount_handler(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        if amount < 10 or amount > 100:
            raise ValueError
        
        data = await state.get_data()
        prediction_id = data['prediction_id']
        choice = data['choice']
        
        user_id = message.from_user.id
        await db.place_bet(user_id, prediction_id, choice, amount)
        await message.answer(f"Bet placed successfully! You bet {amount} tokens on {choice.upper()}.")
        await state.clear()
    except ValueError:
        await message.answer("Invalid amount. Please enter a value between 10 and 100.")

@dp.callback_query(F.data.startswith("resolve_"))
async def resolve_prediction_handler(callback_query: types.CallbackQuery):
    data = callback_query.data.split("_")
    prediction_id, result = data[2], data[1]
    user_id = callback_query.from_user.id
    
    try:
        await db.resolve_prediction(user_id, prediction_id, result)
        await callback_query.message.answer(f"Prediction resolved as '{result.upper()}'. Rewards distributed.")
    except ValueError as e:
        await callback_query.message.answer(f"Error: {str(e)}")
    await callback_query.answer()

# Wallet handlers
@dp.message(PredictionStates.awaiting_wallet_address)
async def wallet_address_handler(message: types.Message, state: FSMContext):
    wallet_address = message.text
    user_id = message.from_user.id
    await db.update_user_wallet(user_id, wallet_address)
    await message.answer("Wallet address saved successfully.")
    await state.clear()

# Referral handlers
@dp.message(CommandStart(deep_link=True))
async def handle_referral(message: types.Message):
    args = message.text.split()[1]
    if args.startswith('ref_'):
        try:
            referrer_id = int(args.split('_')[1])
            user_id = message.from_user.id
            success = await db.add_referral(user_id, referrer_id)
            if success:
                await message.answer("Thanks for using the referral link! You and your referrer got bonus points!")
            else:
                await message.answer("You've already been referred or there was an error.")
        except ValueError as e:
            await message.answer(str(e))
    await start_handler(message)

# Admin management handlers
@dp.message(Command("addadmin"))
async def add_admin_command(message: types.Message, state: FSMContext):
    if not await db.is_bot_owner(message.from_user.id):
        await message.reply("⛔️ This command is only available to the bot owner.")
        return

    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        success = await db.add_admin(user_id)
        if success:
            await message.answer(f"User {user_id} has been added as admin.")
        else:
            await message.answer("Failed to add admin.")
    else:
        await state.set_state(PredictionStates.awaiting_admin_id)
        await message.answer("Please send the user ID of the new admin.")

@dp.message(PredictionStates.awaiting_admin_id)
async def admin_id_handler(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        success = await db.add_admin(user_id)
        if success:
            await message.answer(f"User {user_id} has been added as admin.")
        else:
            await message.answer("Failed to add admin.")
    except ValueError:
        await message.answer("Invalid user ID. Please send a valid numeric ID.")
    finally:
        await state.clear()

# KOL management handlers
@dp.message(Command("addkol"))
async def add_kol_command(message: types.Message, state: FSMContext):
    if not (await db.is_admin(message.from_user.id) or await db.is_bot_owner(message.from_user.id)):
        await message.reply("⛔️ This command is only available to administrators.")
        return

    if message.reply_to_message:
        user_id = message.reply_to_message.from_user.id
        success = await db.add_kol(user_id)
        if success:
            await message.answer(f"User {user_id} has been added as KOL.")
        else:
            await message.answer("Failed to add KOL.")
    else:
        await state.set_state(PredictionStates.awaiting_kol_id)
        await message.answer("Please send the user ID of the new KOL.")

@dp.message(PredictionStates.awaiting_kol_id)
async def kol_id_handler(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
        success = await db.add_kol(user_id)
        if success:
            await message.answer(f"User {user_id} has been added as KOL.")
        else:
            await message.answer("Failed to add KOL.")
    except ValueError:
        await message.answer("Invalid user ID. Please send a valid numeric ID.")
    finally:
        await state.clear()

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


