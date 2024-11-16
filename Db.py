from motor.motor_asyncio import AsyncIOMotorClient

# MongoDB connection
client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["prediction_bot"]

users = db["users"]
predictions = db["predictions"]
bets = db["bets"]

# USERS COLLECTION
async def add_user(user_id):
    """Add a new user to the database."""
    user = await users.find_one({"user_id": user_id})
    if not user:
        await users.insert_one(
            {
                "user_id": user_id,
                "tokens": 100,  # Starting tokens
                "points": 0,  # Starting points
                "wallet": None,  # Wallet details
                "referrals": [],  # List of referrals
                "is_kol": False,  # Whether the user is a KOL
                "is_admin": False,  # Whether the user is an admin
            }
        )

async def get_user(user_id):
    """Fetch user details."""
    return await users.find_one({"user_id": user_id})

async def update_user_balance(user_id, tokens=0, points=0):
    """Update user balance by incrementing tokens and/or points."""
    await users.update_one(
        {"user_id": user_id},
        {"$inc": {"tokens": tokens, "points": points}}
    )

async def update_wallet(user_id, wallet, chain):
    """Update user's wallet details."""
    await users.update_one(
        {"user_id": user_id},
        {"$set": {"wallet": {"address": wallet, "chain": chain}}}
    )

async def get_user_balance(user_id):
    """Get the user's token and point balances."""
    user = await get_user(user_id)
    return {"tokens": user["tokens"], "points": user["points"]}

async def add_referral(referrer_id, referred_user_id):
    """Add a referral and update referrer's rewards."""
    await users.update_one(
        {"user_id": referrer_id},
        {"$push": {"referrals": referred_user_id}}
    )

# PREDICTIONS COLLECTION
async def create_prediction(question, options, timeline, created_by):
    """Create a new prediction."""
    result = await predictions.insert_one(
        {
            "question": question,
            "options": options,  # Example: ["yes", "no"]
            "timeline": timeline,
            "created_by": created_by,
            "status": "active",  # "active" or "resolved"
            "bets": {},  # Bets: {"yes": 0, "no": 0}
            "bidders": []  # List of user bids
        }
    )
    return result.inserted_id

async def get_prediction(prediction_id):
    """Fetch a prediction by its ID."""
    return await predictions.find_one({"_id": prediction_id})

async def update_prediction_bets(prediction_id, choice, amount):
    """Update the bets for a prediction."""
    await predictions.update_one(
        {"_id": prediction_id},
        {"$inc": {f"bets.{choice}": amount}}
    )

async def add_bid_to_prediction(prediction_id, user_id, choice, amount):
    """Add a user's bid to the prediction."""
    await predictions.update_one(
        {"_id": prediction_id},
        {"$push": {"bidders": {"user_id": user_id, "choice": choice, "amount": amount}}}
    )

async def resolve_prediction(prediction_id, correct_choice):
    """Resolve a prediction."""
    await predictions.update_one(
        {"_id": prediction_id},
        {"$set": {"status": "resolved", "correct_choice": correct_choice}}
    )

async def get_active_predictions():
    """Fetch all active predictions."""
    return await predictions.find({"status": "active"}).to_list(None)

async def get_user_predictions(user_id):
    """Fetch all predictions created by a user."""
    return await predictions.find({"created_by": user_id}).to_list(None)

# BETS COLLECTION
async def place_bet(user_id, prediction_id, choice, amount):
    """Place a bet on a prediction."""
    await bets.insert_one(
        {
            "user_id": user_id,
            "prediction_id": prediction_id,
            "choice": choice,
            "amount": amount
        }
    )

async def get_bets_by_prediction(prediction_id):
    """Fetch all bets placed on a specific prediction."""
    return await bets.find({"prediction_id": prediction_id}).to_list(None)

async def get_bidders(prediction_id):
    """Fetch all bidders for a specific prediction."""
    return await predictions.find_one({"_id": prediction_id}, {"bidders": 1})["bidders"]

# LEADERBOARD
async def get_leaderboard():
    """Get top users based on tokens earned."""
    return await users.find().sort("tokens", -1).limit(10).to_list(None)

# KOL MANAGEMENT
async def add_kol(user_id):
    """Add a KOL."""
    await users.update_one({"user_id": user_id}, {"$set": {"is_kol": True}})

async def is_kol(user_id):
    """Check if a user is a KOL."""
    user = await get_user(user_id)
    return user.get("is_kol", False)

# ADMIN MANAGEMENT
async def add_admin(user_id):
    """Add an admin."""
    await users.update_one({"user_id": user_id}, {"$set": {"is_admin": True}})

async def is_admin(user_id):
    """Check if a user is an admin."""
    user = await get_user(user_id)
    return user.get("is_admin", False)
