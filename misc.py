from pytz import timezone, UnknownTimeZoneError
from datetime import datetime
import asyncio

# Broadcast notifications asynchronously
async def broadcast_notifications(bot, user_ids, message):
    for user_id in user_ids:
        try:
            await bot.send_message(chat_id=user_id, text=message)
        except Exception as e:
            print(f"Error sending message to user {user_id}: {e}")

# Automatically resolve bets
async def resolve_bets(bot, db):
    current_time = datetime.utcnow()
    predictions = await db.get_expired_predictions(current_time)
    
    for prediction in predictions:
        try:
            # Resolve prediction and distribute rewards
            resolved_data = await resolve_single_prediction(prediction, db)
            
            # Notify participants
            message = f"Prediction '{prediction['question']}' resolved.\n"
            message += f"The winning choice is: {resolved_data['winning_choice']}.\n"
            message += f"Top winner: {resolved_data['top_winner']} with {resolved_data['top_amount']} tokens!"
            await broadcast_notifications(bot, resolved_data['user_ids'], message)

            # Mark as resolved in DB
            await db.mark_prediction_resolved(prediction["_id"])
        except Exception as e:
            print(f"Error resolving prediction {prediction['_id']}: {e}")

async def resolve_single_prediction(prediction, db):
    # Calculate rewards for each option
    option1_total = sum(bet['amount'] for bet in prediction['bets'] 
                       if bet['choice'] == prediction['options']['option1'])
    option2_total = sum(bet['amount'] for bet in prediction['bets'] 
                       if bet['choice'] == prediction['options']['option2'])

    winning_choice = prediction['options']['option1'] if option1_total > option2_total else prediction['options']['option2']
    winners = [bet for bet in prediction['bets'] if bet['choice'] == winning_choice]
    total_pool = option1_total + option2_total
    reward_pool = option2_total if winning_choice == prediction['options']['option1'] else option1_total

    resolved_data = {
        "winning_choice": winning_choice,
        "user_ids": [],
        "top_winner": None,
        "top_amount": 0
    }

    for winner in winners:
        user_reward = (winner['amount'] / total_pool) * reward_pool
        resolved_data['user_ids'].append(winner['user_id'])
        if user_reward > resolved_data['top_amount']:
            resolved_data['top_winner'] = winner['user_id']
            resolved_data['top_amount'] = user_reward
        
        await db.update_user_balance(winner['user_id'], user_reward)

    return resolved_data

# Convert user timezones safely
def convert_to_timezone(user_time, user_timezone):
    try:
        local_tz = timezone(user_timezone)
        local_time = user_time.astimezone(local_tz)
        return local_time
    except UnknownTimeZoneError:
        return None

def to_utc(local_time, user_timezone):
    """Convert local time to UTC"""
    try:
        local_tz = timezone(user_timezone)
        utc_tz = timezone('UTC')
        # If datetime is naive, assume it's in user's timezone
        if local_time.tzinfo is None:
            local_time = local_tz.localize(local_time)
        return local_time.astimezone(utc_tz)
    except UnknownTimeZoneError:
        return None

def from_utc(utc_time, user_timezone):
    """Convert UTC time to user's local timezone"""
    try:
        local_tz = timezone(user_timezone)
        # If datetime is naive, assume it's UTC
        if utc_time.tzinfo is None:
            utc_time = timezone('UTC').localize(utc_time)
        return utc_time.astimezone(local_tz)
    except UnknownTimeZoneError:
        return None
