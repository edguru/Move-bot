import random
import string
from datetime import datetime, timedelta
from typing import List, Dict
from .db import get_user, add_referral, update_user_balance, get_user_balance, add_kol, is_kol, is_admin, get_active_predictions, get_prediction, update_prediction_bets, add_bid_to_prediction, resolve_prediction, get_bets_by_prediction, get_bidders

# Helper Functions
def generate_referral_code(length=6) -> str:
    """Generates a random referral code consisting of letters and numbers."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def calculate_reward(amount_bet: int, total_bets: int, correct_choice: str, bet_choice: str) -> float:
    """Calculates the reward for each bet based on the total amount and the correct answer."""
    if bet_choice == correct_choice:
        return amount_bet * (total_bets / amount_bet)  # Distribute proportionally
    return 0

def distribute_rewards(prediction_id: str, correct_choice: str) -> None:
    """Distribute rewards to users based on their bets and correct answer."""
    total_bets = {"yes": 0, "no": 0}
    total_amount = {"yes": 0, "no": 0}

    # Get all bets for the prediction
    bets = get_bets_by_prediction(prediction_id)
    for bet in bets:
        total_bets[bet["choice"]] += 1
        total_amount[bet["choice"]] += bet["amount"]

    # Calculate rewards for each bet placed
    for bet in bets:
        reward = calculate_reward(bet["amount"], total_amount[bet["choice"]], correct_choice, bet["choice"])
        # Update the user balance based on the reward
        update_user_balance(bet["user_id"], tokens=reward, points=0)

def send_winner_notification(user_id: str, reward: float) -> None:
    """Send a notification to the winner about their reward."""
    # Placeholder for sending a winner notification (e.g., Telegram message)
    print(f"User {user_id} has won {reward} tokens.")

def generate_prediction_result(prediction_id: str, correct_choice: str) -> str:
    """Generate the result message after a prediction has been resolved."""
    prediction = get_prediction(prediction_id)
    winners = []
    for bet in prediction["bidders"]:
        if bet["choice"] == correct_choice:
            winners.append(bet["user_id"])

    # Reward calculation and sending notification
    for winner in winners:
        reward = calculate_reward(bet["amount"], prediction["bets"][correct_choice], correct_choice, bet["choice"])
        send_winner_notification(winner, reward)

    return f"Prediction {prediction_id} resolved. The correct choice was {correct_choice}. Winners have been notified."

def add_points_for_referral(user_id: str) -> None:
    """Add points and tokens to the user for referring someone."""
    # Add 5 tokens and 10 points for each successful referral
    update_user_balance(user_id, tokens=5, points=10)

async def create_prediction_question(user_id: str, question: str, options: List[str], timeline: int) -> str:
    """Create a prediction question. Only KOLs can create predictions."""
    if not await is_kol(user_id):
        return "You need to be a KOL to create a prediction."

    prediction_id = await create_prediction(question, options, timeline, user_id)
    return f"Prediction '{question}' created successfully with ID: {prediction_id}"

async def add_to_referrals(referrer_id: str, referred_user_id: str) -> None:
    """Add a referral and give rewards."""
    await add_referral(referrer_id, referred_user_id)
    # Adding 5 tokens and 10 points for the referrer
    await add_points_for_referral(referrer_id)

def update_prediction_choices(prediction_id: str, choice: str, amount: int) -> None:
    """Update the prediction with a user's bet."""
    # Update the bets for the prediction
    update_prediction_bets(prediction_id, choice, amount)
    
def place_bet_on_prediction(user_id: str, prediction_id: str, choice: str, amount: int) -> None:
    """Place a bet on a prediction."""
    # Ensure the user has enough tokens to place the bet
    user_balance = get_user_balance(user_id)
    if user_balance["tokens"] < amount:
        print("Insufficient tokens.")
        return

    # Update the user's balance and place the bet
    update_user_balance(user_id, tokens=-amount, points=-20)  # Subtract tokens and points
    add_bid_to_prediction(prediction_id, user_id, choice, amount)

async def get_top_users_by_tokens() -> List[Dict]:
    """Get the top 10 users based on tokens earned."""
    return await get_leaderboard()

async def get_active_predictions_list() -> List[Dict]:
    """Get all active predictions."""
    return await get_active_predictions()

async def resolve_prediction_for_user(prediction_id: str, correct_choice: str) -> str:
    """Resolve a prediction and distribute rewards."""
    distribute_rewards(prediction_id, correct_choice)
    return generate_prediction_result(prediction_id, correct_choice)

def add_kol_user(user_id: str) -> str:
    """Add a user as KOL."""
    add_kol(user_id)
    return f"User {user_id} has been added as KOL."

def add_admin_user(user_id: str) -> str:
    """Add a user as Admin."""
    add_admin(user_id)
    return f"User {user_id} has been added as Admin."

async def check_if_user_is_admin(user_id: str) -> bool:
    """Check if the user is an admin."""
    return await is_admin(user_id)
