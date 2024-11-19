from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from datetime import datetime
import os

class Database:
    def __init__(self, mongo_uri, db_name):
        self.client = AsyncIOMotorClient(mongo_uri)
        self.db = self.client[db_name]
        self.users = self.db["users"]
        self.predictions = self.db["predictions"]
        self.bot_owner_id = int(os.getenv("BOT_OWNER_ID"))

    async def create_user(self, user_id):
        existing_user = await self.users.find_one({"user_id": user_id})
        if not existing_user:
            await self.users.insert_one(
                {
                    "user_id": user_id,
                    "balance": 100,  # Default token balance
                    "points": 50,    # Default points
                    "wallet": None,
                    "referrals": 0,
                    "is_kol": False,
                    "is_admin": False
                }
            )

    async def update_user_wallet(self, user_id, wallet_address):
        await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"wallet": wallet_address}}
        )

    async def get_user_balance(self, user_id):
        user = await self.users.find_one({"user_id": user_id})
        return user["balance"] if user else 0

    async def get_user_points(self, user_id):
        user = await self.users.find_one({"user_id": user_id})
        return user["points"] if user else 0

    async def add_prediction_draft(self, user_id, question):
        await self.predictions.insert_one(
            {
                "creator_id": user_id,
                "question": question,
                "created_at": datetime.utcnow(),
                "expiry_time": None,
                "bets": [],
                "resolved": False,
                "result": None
            }
        )

    async def finalize_prediction(self, user_id, expiry_time):
        await self.predictions.update_one(
            {"creator_id": user_id, "expiry_time": None},
            {"$set": {"expiry_time": expiry_time}}
        )

    async def get_active_predictions(self):
        return await self.predictions.find(
            {"resolved": False, "expiry_time": {"$gt": datetime.utcnow()}}
        ).to_list(length=10)

    async def get_user_predictions(self, user_id, active_only=False):
        query = {"creator_id": user_id}
        if active_only:
            query["resolved"] = False
        return await self.predictions.find(query).to_list(length=10)

    async def place_bet(self, user_id, prediction_id, choice, amount):
        prediction = await self.predictions.find_one({"_id": ObjectId(prediction_id)})
        if not prediction or prediction["resolved"]:
            raise ValueError("Prediction not found or already resolved.")

        user = await self.users.find_one({"user_id": user_id})
        if not user or user["balance"] < amount:
            raise ValueError("Insufficient balance.")

        await self.users.update_one(
            {"user_id": user_id},
            {"$inc": {"balance": -amount}}
        )
        await self.predictions.update_one(
            {"_id": ObjectId(prediction_id)},
            {"$push": {"bets": {"user_id": user_id, "choice": choice, "amount": amount}}}
        )

    async def resolve_prediction(self, user_id, prediction_id, result):
        prediction = await self.predictions.find_one(
            {"_id": ObjectId(prediction_id), "creator_id": user_id, "resolved": False}
        )
        if not prediction:
            raise ValueError("Prediction not found or already resolved.")

        await self.predictions.update_one(
            {"_id": ObjectId(prediction_id)},
            {"$set": {"resolved": True, "result": result}}
        )
        await self.distribute_rewards(prediction, result)

    async def distribute_rewards(self, prediction, result):
        bets = prediction["bets"]
        total_pool = sum(bet["amount"] for bet in bets if bet["choice"] == result)
        if total_pool == 0:
            return  # No winners

        winners = [bet for bet in bets if bet["choice"] == result]
        sorted_winners = sorted(winners, key=lambda x: x["amount"], reverse=True)

        for idx, winner in enumerate(sorted_winners):
            reward = (winner["amount"] / total_pool) * total_pool
            await self.users.update_one(
                {"user_id": winner["user_id"]},
                {"$inc": {"balance": reward}}
            )

    async def automatic_resolution(self):
        expired_predictions = await self.predictions.find(
            {"expiry_time": {"$lte": datetime.utcnow()}, "resolved": False}
        ).to_list(length=10)

        for prediction in expired_predictions:
            await self.resolve_prediction(
                prediction["creator_id"], str(prediction["_id"]), "No Result"
            )

    async def add_kol(self, user_id):
        result = await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_kol": True}}
        )
        return result.modified_count > 0

    async def add_admin(self, user_id):
        result = await self.users.update_one(
            {"user_id": user_id},
            {"$set": {"is_admin": True}}
        )
        return result.modified_count > 0

    async def is_kol(self, user_id):
        user = await self.users.find_one({"user_id": user_id})
        return user and user.get("is_kol", False)

    async def is_admin(self, user_id):
        user = await self.users.find_one({"user_id": user_id})
        return user and user.get("is_admin", False)

    async def is_bot_owner(self, user_id):
        return user_id == self.bot_owner_id