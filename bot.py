import os
import time
import telebot

from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

from pymongo import MongoClient, DESCENDING
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread


# =========================================================
# RENDER KEEP-ALIVE SERVER
# =========================================================

app = Flask(__name__)


@app.route('/')
def home():
    return "Bot is running and healthy!"


def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# =========================================================
# CONFIGURATION
# =========================================================

BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGO_URI = os.getenv('MONGO_URI')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
UPI_ID = os.getenv('UPI_ID', '')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME', '').replace("@", "")

if not BOT_TOKEN or not MONGO_URI or not ADMIN_ID:
    raise ValueError("BOT_TOKEN, MONGO_URI and ADMIN_ID are required!")

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client['sub_management']


# =========================================================
# DATABASE COLLECTIONS
# =========================================================

# Old collections - preserved
channels_col = db['channels']
users_col = db['users']

# New system collections
bot_users_col = db['bot_users']
settings_col = db['settings']
force_channels_col = db['force_channels']
coupons_col = db['coupons']
coupon_uses_col = db['coupon_uses']
feedback_col = db['feedback']


# =========================================================
# TEMPORARY PAYMENT STORAGE
# =========================================================

pending_payments = {}


# =========================================================
# SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "_id": "bot_settings",

    "coin_name": "Coins",
    "coin_emoji": "🪙",
    "referral_reward": 10,

    "reward_channel_id": None,
    "reward_channel_name": "Premium Channel",

    "reward_1_day_cost": 50,
    "reward_7_day_cost": 250,
    "reward_30_day_cost": 800,

    "welcome_text": "✨ *Welcome!*\\n\\nChoose an option below.",

    "how_it_works_text": (
        "📖 *How It Works*\\n\\n"
        "1️⃣ Share your referral link.\\n"
        "2️⃣ Your friend starts the bot using your link.\\n"
        "3️⃣ They join the required channels and verify.\\n"
        "4️⃣ You receive coins automatically.\\n"
        "5️⃣ Redeem your coins for Premium membership!"
    )
}


def get_settings():
    settings = settings_col.find_one({"_id": "bot_settings"})

    if not settings:
        settings_col.insert_one(DEFAULT_SETTINGS.copy())
        settings = DEFAULT_SETTINGS.copy()

    update = {}

    for key, value in DEFAULT_SETTINGS.items():
        if key not in settings:
            update[key] = value

    if update:
        settings_col.update_one(
            {"_id": "bot_settings"},
            {"$set": update}
        )
        settings.update(update)

    return settings


def update_setting(key, value):
    settings_col.update_one(
        {"_id": "bot_settings"},
        {"$set": {key: value}},
        upsert=True
    )


# =========================================================
# USER DATABASE HELPERS
# =========================================================

def get_user(user_id):
    return bot_users_col.find_one({"user_id": user_id})


def register_user(user):
    """Register user without overwriting referral information."""

    bot_users_col.update_one(
        {"user_id": user.id},
        {
            "$setOnInsert": {
                "user_id": user.id,
                "joined_at": datetime.now(),
                "coins": 0,
                "referral_count": 0,
                "verified_referral": False,
                "pending_referrer": None,
                "referrer_id": None
            },
            "$set": {
                "first_name": user.first_name or "",
                "username": user.username or ""
            }
        },
        upsert=True
    )


def get_coin_balance(user_id):
    user = get_user(user_id)
    return user.get("coins", 0) if user else 0


def add_coins(user_id, amount):
    bot_users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"coins": amount}},
        upsert=True
    )


def get_user_display_name(user):
    if not user:
        return "Unknown User"

    name = user.get("first_name") or "User"
    username = user.get("username") or ""

    if username:
        return f"{name} (@{username})"

    return name


# =========================================================
# MAIN USER MENU
# =========================================================

def main_menu(user_id, chat_id=None):

    if chat_id is None:
        chat_id = user_id

    settings = get_settings()

    markup = ReplyKeyboardMarkup(
        resize_keyboard=True,
        row_width=2
    )

    markup.row(
        KeyboardButton("🌐 My Profile"),
        KeyboardButton("🔗 Refer & Earn")
    )

    markup.row(
        KeyboardButton("🎁 Redeem Premium"),
        KeyboardButton("👥 My Referrals")
    )

    markup.row(
        KeyboardButton("🎟 Claim Coupon"),
        KeyboardButton("🏆 Leaderboard")
    )

    markup.row(
        KeyboardButton("💬 Send Feedback"),
        KeyboardButton("📖 How It Works")
    )

    markup.row(
        KeyboardButton("📞 Contact Admin")
    )

    bot.send_message(
        chat_id,
        settings["welcome_text"],
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# FORCE JOIN / REFERRAL VERIFICATION
# =========================================================

def get_force_join_markup():

    markup = InlineKeyboardMarkup()
    channels = list(force_channels_col.find())

    for channel in channels:

        url = channel.get("join_url")

        if url:
            markup.add(
                InlineKeyboardButton(
                    f"📢 Join {channel.get('name', 'Channel')}",
                    url=url
                )
            )

    markup.add(
        InlineKeyboardButton(
            "✅ Verify & Continue",
            callback_data="verify_referral"
        )
    )

    return markup


def show_force_join(chat_id):

    channels = list(force_channels_col.find())

    if not channels:
        bot.send_message(
            chat_id,
            "⚠️ Required verification channels have not been configured yet. Please contact the admin."
        )
        return

    bot.send_message(
        chat_id,
        """🎉 *Welcome!*

You joined using a referral link.

To continue, please join *all required channels/groups* using the buttons below.

After joining them, press *✅ Verify & Continue*.

⚠️ You cannot receive the referral reward until verification is completed.""",
        reply_markup=get_force_join_markup(),
        parse_mode="Markdown"
    )


def is_user_in_channel(channel_id, user_id):
    """Check Telegram membership safely."""

    try:
        member = bot.get_chat_member(channel_id, user_id)

        if member.status in ["creator", "administrator", "member"]:
            return True

        if member.status == "restricted":
            return getattr(member, "is_member", True)

        return False

    except Exception as e:
        print(
            f"Membership check error | "
            f"Channel: {channel_id} | "
            f"User: {user_id} | {e}"
        )
        return False


def check_all_force_channels(user_id):

    channels = list(force_channels_col.find())

    if not channels:
        return False

    for channel in channels:

        if not is_user_in_channel(
            channel["channel_id"],
            user_id
        ):
            return False

    return True


# =========================================================
# START COMMAND
# =========================================================

@bot.message_handler(commands=['start'])
def start_handler(message):

    user_id = message.from_user.id
    register_user(message.from_user)

    parts = message.text.split(maxsplit=1)
    start_argument = parts[1].strip() if len(parts) > 1 else None

    user_data = get_user(user_id)

    # -----------------------------------------------------
    # 1. OLD PAID CHANNEL DEEP LINK
    # -----------------------------------------------------

    if start_argument:

        try:
            possible_channel_id = int(start_argument)

            if possible_channel_id < 0:

                ch_data = channels_col.find_one(
                    {"channel_id": possible_channel_id}
                )

                if ch_data:

                    markup = InlineKeyboardMarkup()

                    # Original demo button preserved
                    rejoin_url = "https://t.me/+lSW2hYbgrUNkMzFl"

                    markup.add(
                        InlineKeyboardButton(
                            "🔗 Demo",
                            url=rejoin_url
                        )
                    )

                    for p_time, p_price in ch_data["plans"].items():

                        minutes = int(p_time)

                        if minutes > 525600:
                            label = "💎 Lifetime"
                        elif minutes >= 1440:
                            label = f"📅 {minutes // 1440} Days"
                        else:
                            label = f"⏱ {minutes} Min"

                        markup.add(
                            InlineKeyboardButton(
                                label,
                                callback_data=f"select_{possible_channel_id}_{p_time}"
                            )
                        )

                    if CONTACT_USERNAME:
                        markup.add(
                            InlineKeyboardButton(
                                "📞 Contact Admin",
                                url=f"https://t.me/{CONTACT_USERNAME}"
                            )
                        )

                    bot.send_message(
                        message.chat.id,
                        f"""✨ *Welcome!*

📢 *Channel:* `{ch_data['name']}`

Select a subscription plan below.""",
                        reply_markup=markup,
                        parse_mode="Markdown"
                    )

                    return

        except (ValueError, TypeError):
            pass
        except Exception as e:
            print(f"Paid start error: {e}")

    # -----------------------------------------------------
    # 2. USER WITH PENDING REFERRAL CAN NEVER BYPASS
    # -----------------------------------------------------

    user_data = get_user(user_id)

    if (
        user_data
        and user_data.get("pending_referrer") is not None
        and not user_data.get("verified_referral", False)
    ):
        show_force_join(message.chat.id)
        return

    # -----------------------------------------------------
    # 3. NEW REFERRAL LINK
    # -----------------------------------------------------

    if start_argument:

        try:
            referrer_id = int(start_argument)
            referrer = get_user(referrer_id)

            if (
                referrer_id != user_id
                and referrer is not None
                and user_data.get("pending_referrer") is None
                and user_data.get("referrer_id") is None
                and not user_data.get("verified_referral", False)
            ):

                # Save referral as pending ONLY
                bot_users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "pending_referrer": referrer_id,
                            "referred_at": datetime.now()
                        }
                    }
                )

                show_force_join(message.chat.id)
                return

        except (ValueError, TypeError):
            pass

    # -----------------------------------------------------
    # 4. NORMAL USER
    # -----------------------------------------------------

    if user_id == ADMIN_ID:
        bot.send_message(
            message.chat.id,
            "👑 *Admin Account*\n\nUse /admin to open the admin panel.",
            parse_mode="Markdown"
        )

    main_menu(user_id, message.chat.id)


# =========================================================
# VERIFY REFERRAL
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "verify_referral"
)
def verify_referral(call):

    user_id = call.from_user.id
    user_data = get_user(user_id)

    if not user_data:
        bot.answer_callback_query(
            call.id,
            "Please start the bot again.",
            show_alert=True
        )
        return

    if user_data.get("pending_referrer") is None:
        bot.answer_callback_query(
            call.id,
            "No pending referral verification found.",
            show_alert=True
        )
        return

    if user_data.get("verified_referral", False):
        bot.answer_callback_query(
            call.id,
            "You are already verified!",
            show_alert=True
        )
        return

    # Check all channels
    if not check_all_force_channels(user_id):
        bot.answer_callback_query(
            call.id,
            "❌ You haven't joined all required channels yet.",
            show_alert=True
        )
        return

    referrer_id = user_data["pending_referrer"]
    settings = get_settings()
    reward = int(settings.get("referral_reward", 10))

    # Process only once
    result = bot_users_col.update_one(
        {
            "user_id": user_id,
            "verified_referral": False,
            "pending_referrer": referrer_id
        },
        {
            "$set": {
                "verified_referral": True,
                "referrer_id": referrer_id,
                "pending_referrer": None,
                "verified_at": datetime.now()
            }
        }
    )

    if result.modified_count != 1:
        bot.answer_callback_query(
            call.id,
            "This referral was already processed.",
            show_alert=True
        )
        return

    # Reward referrer
    bot_users_col.update_one(
        {"user_id": referrer_id},
        {
            "$inc": {
                "coins": reward,
                "referral_count": 1
            }
        }
    )

    bot.answer_callback_query(
        call.id,
        "✅ Verification successful!"
    )

    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass

    # Get the latest user data
    referred_user = get_user(user_id)
    referred_name = get_user_display_name(referred_user)

    coin_name = settings["coin_name"]
    coin_emoji = settings["coin_emoji"]

    # Notify referrer
    try:
        bot.send_message(
            referrer_id,
            f"""🎉 *New Successful Referral!*

👤 *{referred_name}* successfully joined through your referral link!

{coin_emoji} You received *{reward} {coin_name}*.

👥 Your referral has been counted successfully!""",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Referral notification error: {e}")

    bot.send_message(
        user_id,
        """✅ *Verification Successful!*

Welcome! You can now use all bot features.""",
        parse_mode="Markdown"
    )

    main_menu(user_id)


# =========================================================
# USER PROFILE
# =========================================================

@bot.message_handler(func=lambda m: m.text == "🌐 My Profile")
def my_profile(message):

    user_id = message.from_user.id
    user = get_user(user_id)
    settings = get_settings()

    if not user:
        register_user(message.from_user)
        user = get_user(user_id)

    joined = user.get("joined_at")

    if isinstance(joined, datetime):
        joined_text = joined.strftime("%d %b %Y")
    else:
        joined_text = "Unknown"

    # Who referred the user?
    referrer_text = "No one"

    referrer_id = user.get("referrer_id")

    if referrer_id:
        referrer = get_user(referrer_id)

        if referrer:
            referrer_text = get_user_display_name(referrer)

    # Active memberships
    now = datetime.now().timestamp()

    active_memberships = list(
        users_col.find({
            "user_id": user_id,
            "expiry": {"$gt": now}
        })
    )

    premium_text = "✅ Active" if active_memberships else "❌ No Active Premium"

    bot.send_message(
        message.chat.id,
        f"""👤 *My Profile*

👤 *Name:* {user.get('first_name') or 'User'}
🆔 *User ID:* `{user_id}`
📅 *Joined:* {joined_text}

{settings['coin_emoji']} *Balance:* {user.get('coins', 0)} {settings['coin_name']}
👥 *Successful Referrals:* {user.get('referral_count', 0)}

🔗 *Referred By:* {referrer_text}
💎 *Premium:* {premium_text}""",
        parse_mode="Markdown"
    )


# =========================================================
# REFER & EARN
# =========================================================

@bot.message_handler(func=lambda m: m.text == "🔗 Refer & Earn")
def refer_and_earn(message):

    user_id = message.from_user.id
    user = get_user(user_id)
    settings = get_settings()

    try:
        username = bot.get_me().username
        link = f"https://t.me/{username}?start={user_id}"
    except Exception:
        link = "Unable to generate referral link."

    bot.send_message(
        message.chat.id,
        f"""🔗 *Refer & Earn*

🎁 *Reward per successful referral:*
{settings['coin_emoji']} {settings['referral_reward']} {settings['coin_name']}

👥 *Successful Referrals:* {user.get('referral_count', 0)}

🔗 *Your Referral Link:*

`{link}`

📌 Your friend must join all required channels and complete verification before you receive the reward.""",
        parse_mode="Markdown"
    )


# =========================================================
# MY REFERRALS
# =========================================================

@bot.message_handler(func=lambda m: m.text == "👥 My Referrals")
def my_referrals(message):

    user_id = message.from_user.id

    referrals = list(
        bot_users_col.find({
            "referrer_id": user_id,
            "verified_referral": True
        })
        .sort("verified_at", DESCENDING)
        .limit(30)
    )

    if not referrals:
        bot.send_message(
            message.chat.id,
            """👥 *My Referrals*

You haven't successfully referred anyone yet.

Share your referral link and earn coins when your friends complete verification!""",
            parse_mode="Markdown"
        )
        return

    text = "👥 *My Successful Referrals*\n\n"

    for number, referred_user in enumerate(referrals, start=1):
        text += f"{number}. {get_user_display_name(referred_user)}\n"

    total = bot_users_col.count_documents({
        "referrer_id": user_id,
        "verified_referral": True
    })

    text += f"\n🎉 *Total Successful Referrals:* {total}"

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# HOW IT WORKS
# =========================================================

@bot.message_handler(func=lambda m: m.text == "📖 How It Works")
def how_it_works(message):

    settings = get_settings()

    bot.send_message(
        message.chat.id,
        settings["how_it_works_text"],
        parse_mode="Markdown"
    )


# =========================================================
# CONTACT ADMIN
# =========================================================

@bot.message_handler(func=lambda m: m.text == "📞 Contact Admin")
def contact_admin(message):

    if not CONTACT_USERNAME:
        bot.send_message(
            message.chat.id,
            "⚠️ Contact information has not been configured yet."
        )
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    bot.send_message(
        message.chat.id,
        "📞 *Need help?*\n\nContact the admin below:",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# FEEDBACK SYSTEM
# =========================================================

@bot.message_handler(func=lambda m: m.text == "💬 Send Feedback")
def feedback_start(message):

    msg = bot.send_message(
        message.chat.id,
        """💬 *Send Feedback*

Please send your feedback, suggestion, or report in one message.

Your feedback will be delivered directly to the admin.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        receive_feedback
    )


def receive_feedback(message):

    if not message.text:
        bot.send_message(
            message.chat.id,
            "❌ Please send your feedback as text."
        )
        return

    user_id = message.from_user.id

    feedback_col.insert_one({
        "user_id": user_id,
        "first_name": message.from_user.first_name or "",
        "username": message.from_user.username or "",
        "feedback": message.text,
        "created_at": datetime.now(),
        "status": "new"
    })

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "No username"
    )

    try:
        bot.send_message(
            ADMIN_ID,
            f"""💬 *New User Feedback*

👤 Name: {message.from_user.first_name}
🌐 Username: {username}
🆔 User ID: `{user_id}`

📝 *Feedback:*
{message.text}""",
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Feedback error: {e}")

    bot.send_message(
        message.chat.id,
        "✅ *Feedback Sent!*\n\nThank you for helping us improve ❤️",
        parse_mode="Markdown"
    )


# =========================================================
# REDEEM PREMIUM
# =========================================================

@bot.message_handler(func=lambda m: m.text == "🎁 Redeem Premium")
def redeem_premium_menu(message):

    settings = get_settings()

    if not settings.get("reward_channel_id"):
        bot.send_message(
            message.chat.id,
            "⚠️ Premium rewards are not available yet."
        )
        return

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            f"🎁 1 Day — {settings['reward_1_day_cost']} {settings['coin_name']}",
            callback_data="redeem_1"
        )
    )

    markup.add(
        InlineKeyboardButton(
            f"🎁 7 Days — {settings['reward_7_day_cost']} {settings['coin_name']}",
            callback_data="redeem_7"
        )
    )

    markup.add(
        InlineKeyboardButton(
            f"🎁 30 Days — {settings['reward_30_day_cost']} {settings['coin_name']}",
            callback_data="redeem_30"
        )
    )

    bot.send_message(
        message.chat.id,
        f"""🎁 *Redeem Premium*

{settings['coin_emoji']} Your balance: *{get_coin_balance(message.from_user.id)} {settings['coin_name']}*

Choose a reward below:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("redeem_")
)
def redeem_premium(call):

    settings = get_settings()
    user_id = call.from_user.id

    reward_map = {
        "redeem_1": (1, int(settings["reward_1_day_cost"])),
        "redeem_7": (7, int(settings["reward_7_day_cost"])),
        "redeem_30": (30, int(settings["reward_30_day_cost"]))
    }

    if call.data not in reward_map:
        return

    days, cost = reward_map[call.data]
    channel_id = settings.get("reward_channel_id")

    if not channel_id:
        bot.answer_callback_query(
            call.id,
            "Premium channel is not configured.",
            show_alert=True
        )
        return

    # Deduct coins only when enough balance exists
    result = bot_users_col.update_one(
        {
            "user_id": user_id,
            "coins": {"$gte": cost}
        },
        {
            "$inc": {"coins": -cost}
        }
    )

    if result.modified_count != 1:
        bot.answer_callback_query(
            call.id,
            "❌ You don't have enough coins!",
            show_alert=True
        )
        return

    try:
        expiry_datetime = datetime.now() + timedelta(days=days)

        link = bot.create_chat_invite_link(
            channel_id,
            member_limit=1,
            expire_date=int(expiry_datetime.timestamp())
        )

        users_col.update_one(
            {
                "user_id": user_id,
                "channel_id": channel_id
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp(),
                    "source": "coin_reward",
                    "reward_days": days
                }
            },
            upsert=True
        )

        bot.answer_callback_query(
            call.id,
            "🎉 Premium redeemed!"
        )

        bot.send_message(
            user_id,
            f"""🎉 *Premium Redeemed Successfully!*

🎁 *Reward:* {days} Day Premium
⏰ *Expires:* {expiry_datetime.strftime("%d %b %Y, %H:%M")}

🔗 *Join Premium Channel:*
{link.invite_link}

⚠️ This link can only be used once.

After your Premium time ends, you will automatically be removed from the Premium channel.""",
            parse_mode="Markdown"
        )

    except Exception as e:

        # Refund if something failed
        add_coins(user_id, cost)

        print(f"Redeem error: {e}")

        bot.answer_callback_query(
            call.id,
            "❌ Something went wrong. Your coins were refunded.",
            show_alert=True
        )


# =========================================================
# COUPON SYSTEM
# =========================================================

@bot.message_handler(func=lambda m: m.text == "🎟 Claim Coupon")
def claim_coupon_prompt(message):

    msg = bot.send_message(
        message.chat.id,
        "🎟 Send the coupon code you want to claim."
    )

    bot.register_next_step_handler(
        msg,
        process_coupon
    )


def process_coupon(message):

    if not message.text:
        bot.send_message(message.chat.id, "❌ Please send a valid coupon code.")
        return

    code = message.text.strip().upper()
    user_id = message.from_user.id
    settings = get_settings()

    coupon = coupons_col.find_one({"code": code})

    if not coupon:
        bot.send_message(message.chat.id, "❌ Invalid coupon code.")
        return

    if coupon.get("expires_at") and coupon["expires_at"] < datetime.now():
        bot.send_message(message.chat.id, "⌛ This coupon has expired.")
        return

    if coupon.get("used_count", 0) >= coupon.get("max_uses", 1):
        bot.send_message(message.chat.id, "❌ This coupon has reached its usage limit.")
        return

    already_used = coupon_uses_col.find_one({
        "coupon_code": code,
        "user_id": user_id
    })

    if already_used:
        bot.send_message(message.chat.id, "⚠️ You have already used this coupon.")
        return

    result = coupons_col.update_one(
        {
            "code": code,
            "used_count": {"$lt": coupon.get("max_uses", 1)}
        },
        {
            "$inc": {"used_count": 1}
        }
    )

    if result.modified_count != 1:
        bot.send_message(message.chat.id, "❌ Coupon is no longer available.")
        return

    try:
        coupon_uses_col.insert_one({
            "coupon_code": code,
            "user_id": user_id,
            "claimed_at": datetime.now()
        })

        coins = int(coupon["coins"])
        add_coins(user_id, coins)

        bot.send_message(
            message.chat.id,
            f"""🎉 *Coupon Claimed Successfully!*

{settings['coin_emoji']} You received *{coins} {settings['coin_name']}*.""",
            parse_mode="Markdown"
        )

    except Exception as e:
        # Note: usage was reserved. Admin can inspect database if this rare failure happens.
        print(f"Coupon claim error: {e}")
        bot.send_message(
            message.chat.id,
            "❌ Something went wrong while claiming the coupon."
        )


# =========================================================
# LEADERBOARD
# =========================================================

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):

    users = list(
        bot_users_col.find(
            {"referral_count": {"$gt": 0}}
        ).sort(
            "referral_count",
            DESCENDING
        ).limit(10)
    )

    if not users:
        bot.send_message(
            message.chat.id,
            "🏆 No successful referrals yet."
        )
        return

    text = "🏆 *Referral Leaderboard*\n\n"

    for position, user in enumerate(users, start=1):
        text += (
            f"{position}. {user.get('first_name') or 'User'} — "
            f"*{user.get('referral_count', 0)} referrals*\n"
        )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# OLD ADMIN CHANNEL MANAGEMENT - PRESERVED
# =========================================================

@bot.message_handler(
    commands=['channels'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_channels(message):

    markup = InlineKeyboardMarkup()
    cursor = channels_col.find({"admin_id": ADMIN_ID})
    count = 0

    for ch in cursor:
        markup.add(
            InlineKeyboardButton(
                f"📢 {ch['name']}",
                callback_data=f"manage_{ch['channel_id']}"
            )
        )
        count += 1

    markup.add(
        InlineKeyboardButton(
            "➕ Add New Channel",
            callback_data="add_new"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "Your Managed Channels:" if count else "No channels found. Click below to add one.",
        reply_markup=markup
    )


@bot.message_handler(
    commands=['add'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Please ensure the bot is an Admin in your channel.\n\nThen FORWARD any message from that channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def cb_add_new(call):

    if call.from_user.id != ADMIN_ID:
        return

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        "Please FORWARD any message from your channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


def get_plans(message):

    if message.forward_from_chat:

        ch_id = message.forward_from_chat.id
        ch_name = message.forward_from_chat.title

        msg = bot.send_message(
            ADMIN_ID,
            f"""✅ Channel Detected: {ch_name}

Enter plans in this format:

`1440:99,43200:199`

1440 = 1 Day
43200 = 30 Days""",
            parse_mode="Markdown"
        )

        bot.register_next_step_handler(
            msg,
            finalize_channel,
            ch_id,
            ch_name
        )

    else:
        bot.send_message(
            ADMIN_ID,
            "❌ Error: Message was not forwarded. Use /add again."
        )


def finalize_channel(message, ch_id, ch_name):

    try:
        raw_plans = message.text.split(",")
        plans_dict = {}

        for p in raw_plans:
            t, pr = p.strip().split(":")
            plans_dict[t] = pr

        channels_col.update_one(
            {"channel_id": ch_id},
            {
                "$set": {
                    "name": ch_name,
                    "plans": plans_dict,
                    "admin_id": ADMIN_ID
                }
            },
            upsert=True
        )

        bot_username = bot.get_me().username

        bot.send_message(
            ADMIN_ID,
            f"""✅ Setup Successful!

Invite Link:
`https://t.me/{bot_username}?start={ch_id}`""",
            parse_mode="Markdown"
        )

    except Exception as e:

        print(e)

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\nUse:\n`1440:99,43200:199`",
            parse_mode="Markdown"
        )


# =========================================================
# OLD PAYMENT FLOW - PRESERVED
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("select_")
)
def user_pays(call):

    _, ch_id, mins = call.data.split("_")

    ch_data = channels_col.find_one(
        {"channel_id": int(ch_id)}
    )

    if not ch_data:
        bot.answer_callback_query(call.id, "Channel not found.")
        return

    price = float(ch_data["plans"][mins])

    USD_RATE = 100
    INR_RATE = 2

    usd_price = price / USD_RATE
    inr_price = price / INR_RATE
    minutes = int(mins)

    if minutes > 525600:
        plan_name = "💎 Lifetime"
    elif minutes >= 1440:
        plan_name = f"📅 {minutes // 1440} Days"
    else:
        plan_name = f"⏱ {minutes} Min"

    qr_url = "https://i.ibb.co/v4yw96tb/IMG-20260712-103503.jpg"

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "✅ I Have Paid",
            callback_data=f"paid_{ch_id}_{mins}"
        )
    )

    if CONTACT_USERNAME:
        markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )

    bot.send_photo(
        call.message.chat.id,
        qr_url,
        caption=(
            f"📢 *{ch_data['name']}*\n\n"
            f"💎 *Plan:* {plan_name}\n\n"
            f"💰 *Price*\n"
            f"🇳🇵 NPR: {price:.0f}\n"
            f"🇺🇸 USD: ${usd_price:.2f}\n"
            f"🇮🇳 INR: ₹{inr_price:.2f}\n\n"
            "━━━━━━━━━━━━━━\n"
            "⚠️ *This QR is for Nepali users only.*\n\n"
            f"*Binance ID:*\n`{UPI_ID}`\n\n"
            "📋 Tap the payment details to copy them.\n\n"
            "✅ After payment, tap *I Have Paid*.\n"
            "📷 Then send your payment screenshot."
        ),
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("paid_")
)
def payment_screenshot_request(call):

    _, ch_id, mins = call.data.split("_")
    user_id = call.from_user.id

    if user_id in pending_payments:
        bot.answer_callback_query(
            call.id,
            "⚠️ You already have a pending payment verification.",
            show_alert=True
        )
        return

    ch_data = channels_col.find_one(
        {"channel_id": int(ch_id)}
    )

    if not ch_data:
        return

    pending_payments[user_id] = {
        "channel_id": int(ch_id),
        "channel_name": ch_data["name"],
        "plan": mins,
        "price": ch_data["plans"][mins],
        "time": datetime.now()
    }

    bot.answer_callback_query(call.id)

    bot.send_message(
        user_id,
        """📷 *Upload Payment Screenshot*

Please send your payment screenshot as a *PHOTO*.

Once uploaded, it will be forwarded to the admin.

⏳ Please upload it within 10 minutes.""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=['text']
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "📷 Please upload your payment screenshot as a PHOTO."
    )


@bot.message_handler(content_types=['document'])
def document_handler(message):

    if message.from_user.id not in pending_payments:
        return

    bot.reply_to(
        message,
        "❌ Please send the payment screenshot as a PHOTO, not as a document."
    )


@bot.message_handler(content_types=['photo'])
def photo_handler(message):

    try:

        user_id = message.from_user.id

        if user_id not in pending_payments:
            return

        payment = pending_payments[user_id]

        bot.forward_message(
            ADMIN_ID,
            message.chat.id,
            message.message_id
        )

        username = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else "No Username"
        )

        bot.send_message(
            ADMIN_ID,
            f"""🔔 Payment Verification Required!

👤 Name: {message.from_user.first_name}
🆔 User ID: {user_id}
🌐 Username: {username}

📢 Channel: {payment['channel_name']}
💎 Plan: {payment['plan']}
💰 Price: NPR {payment['price']}

📷 Screenshot has been forwarded above."""
        )

        markup = InlineKeyboardMarkup(row_width=2)

        markup.add(
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"app_{user_id}_{payment['channel_id']}_{payment['plan']}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"rej_{user_id}"
            )
        )

        bot.send_message(
            ADMIN_ID,
            "👇 Select an action:",
            reply_markup=markup
        )

        bot.send_message(
            user_id,
            """✅ Screenshot Uploaded Successfully!

⏳ Status: Waiting for admin verification.

🔔 Once approved, your invite link will be sent automatically."""
        )

        del pending_payments[user_id]

    except Exception as e:
        print(f"PHOTO_HANDLER ERROR: {e}")


# =========================================================
# OLD PAYMENT APPROVAL SYSTEM
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("app_")
)
def approve_now(call):

    if call.from_user.id != ADMIN_ID:
        return

    _, u_id, ch_id, mins = call.data.split("_")

    u_id = int(u_id)
    ch_id = int(ch_id)
    mins = int(mins)

    try:

        expiry_datetime = datetime.now() + timedelta(minutes=mins)

        link = bot.create_chat_invite_link(
            ch_id,
            member_limit=1,
            expire_date=int(expiry_datetime.timestamp())
        )

        users_col.update_one(
            {
                "user_id": u_id,
                "channel_id": ch_id
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp(),
                    "source": "paid_subscription"
                }
            },
            upsert=True
        )

        if mins > 525600:
            plan_name = "💎 Lifetime"
        elif mins >= 1440:
            plan_name = f"📅 {mins // 1440} Days"
        else:
            plan_name = f"⏱ {mins} Minutes"

        bot.send_message(
            u_id,
            f"""🎉 *Payment Approved!*

Your payment has been verified successfully.

💎 *Plan:* {plan_name}

🔗 *Join Link:*
{link.invite_link}

⚠️ This invite link can only be used once.""",
            parse_mode="Markdown"
        )

        bot.edit_message_text(
            "✅ Payment Approved Successfully.",
            call.message.chat.id,
            call.message.message_id
        )

    except Exception as e:
        print(f"Approval error: {e}")

        bot.send_message(
            ADMIN_ID,
            f"❌ Error:\n{e}"
        )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("rej_")
)
def reject_payment(call):

    if call.from_user.id != ADMIN_ID:
        return

    user_id = int(call.data.split("_")[1])

    pending_payments.pop(user_id, None)

    try:
        bot.send_message(
            user_id,
            """❌ *Payment Rejected*

Your payment could not be verified.

If you believe this is a mistake, contact the admin.""",
            parse_mode="Markdown"
        )
    except Exception:
        pass

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# ADMIN PANEL
# =========================================================

@bot.message_handler(
    commands=['admin'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def admin_panel(message):

    settings = get_settings()

    bot.send_message(
        ADMIN_ID,
        f"""👑 *Admin Panel*

🪙 Coin: {settings['coin_name']}
🎁 Referral reward: {settings['referral_reward']}
📢 Force-join channels: {force_channels_col.count_documents({})}

*CHANNELS*
📢 `/add` — Add paid subscription channel
📋 `/channels` — View paid channels

*REFERRAL SYSTEM*
📢 `/forceadd` — Add required verification channel
🗑 `/forcelist` — View/remove required channels
🎁 `/setpremium` — Set Premium reward channel

*SETTINGS*
⚙️ `/settings` — View settings
🪙 `/setcoin NAME` — Change coin name
🎁 `/setreward AMOUNT` — Change referral reward
💰 `/setcost DAYS COINS` — Set Premium costs

*COUPONS*
🎟 `/coupon CODE COINS MAX_USERS HOURS`
🗑 `/coupons` — View coupons

*MANAGEMENT*
📢 `/broadcast` — Broadcast to users
📊 `/stats` — Bot statistics
💬 `/feedbacks` — View feedback""",
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN SETTINGS
# =========================================================

@bot.message_handler(
    commands=['settings'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def show_settings(message):

    s = get_settings()

    bot.send_message(
        ADMIN_ID,
        f"""⚙️ *Current Settings*

{s['coin_emoji']} Coin Name: *{s['coin_name']}*
🎁 Referral Reward: *{s['referral_reward']} {s['coin_name']}*

🎁 1 Day Cost: *{s['reward_1_day_cost']}*
🎁 7 Day Cost: *{s['reward_7_day_cost']}*
🎁 30 Day Cost: *{s['reward_30_day_cost']}*

📢 Reward Channel: *{s['reward_channel_name']}*""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=['setcoin'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_coin(message):

    parts = message.text.split(maxsplit=1)

    if len(parts) < 2:
        bot.reply_to(message, "Usage: `/setcoin CoinName`", parse_mode="Markdown")
        return

    update_setting("coin_name", parts[1].strip())

    bot.reply_to(
        message,
        f"✅ Coin name changed to *{parts[1].strip()}*.",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=['setreward'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_referral_reward(message):

    parts = message.text.split()

    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: `/setreward 10`")
        return

    update_setting("referral_reward", int(parts[1]))
    bot.reply_to(message, "✅ Referral reward updated.")


@bot.message_handler(
    commands=['setcost'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_reward_cost(message):

    parts = message.text.split()

    if len(parts) != 3:
        bot.reply_to(message, "Usage: `/setcost 1 50`\nDays: 1, 7 or 30")
        return

    try:

        days = int(parts[1])
        cost = int(parts[2])

        key_map = {
            1: "reward_1_day_cost",
            7: "reward_7_day_cost",
            30: "reward_30_day_cost"
        }

        if days not in key_map or cost < 0:
            raise ValueError

        update_setting(key_map[days], cost)

        bot.reply_to(
            message,
            f"✅ {days}-day reward cost updated to {cost}."
        )

    except ValueError:
        bot.reply_to(message, "❌ Usage: `/setcost 1 50`")


# =========================================================
# FORCE JOIN ADMIN
# =========================================================

@bot.message_handler(
    commands=['forceadd'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def force_add_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """📢 Forward a message from the channel/group you want users to join.

⚠️ Make sure the bot is an administrator in that channel/group."""
    )

    bot.register_next_step_handler(msg, save_force_channel)


def save_force_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the channel/group."
        )
        return

    chat = message.forward_from_chat
    channel_id = chat.id
    name = chat.title or "Required Channel"

    if chat.username:
        join_url = f"https://t.me/{chat.username}"
    else:
        try:
            invite = bot.create_chat_invite_link(channel_id)
            join_url = invite.invite_link
        except Exception as e:
            print(f"Force channel invite error: {e}")

            bot.send_message(
                ADMIN_ID,
                "❌ Could not create a join link. Make the bot an admin and try again."
            )
            return

    force_channels_col.update_one(
        {"channel_id": channel_id},
        {
            "$set": {
                "channel_id": channel_id,
                "name": name,
                "join_url": join_url
            }
        },
        upsert=True
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Added required channel: *{name}*",
        parse_mode="Markdown"
    )


@bot.message_handler(
    commands=['forcelist'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def force_list(message):

    channels = list(force_channels_col.find())

    if not channels:
        bot.send_message(ADMIN_ID, "No required channels configured.")
        return

    markup = InlineKeyboardMarkup()

    for channel in channels:
        markup.add(
            InlineKeyboardButton(
                f"🗑 Remove {channel['name']}",
                callback_data=f"force_remove_{channel['channel_id']}"
            )
        )

    bot.send_message(
        ADMIN_ID,
        "📢 *Required Channels*",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("force_remove_")
)
def remove_force_channel(call):

    if call.from_user.id != ADMIN_ID:
        return

    channel_id = int(call.data.replace("force_remove_", ""))

    force_channels_col.delete_one({"channel_id": channel_id})

    bot.answer_callback_query(call.id, "Channel removed!")

    bot.edit_message_text(
        "✅ Required channel removed.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# SET PREMIUM REWARD CHANNEL
# =========================================================

@bot.message_handler(
    commands=['setpremium'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_premium_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """🎁 Forward a message from the Premium reward channel.

⚠️ The bot must be an administrator and have permission to remove members."""
    )

    bot.register_next_step_handler(
        msg,
        save_premium_channel
    )


def save_premium_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the Premium channel."
        )
        return

    chat = message.forward_from_chat

    update_setting("reward_channel_id", chat.id)
    update_setting(
        "reward_channel_name",
        chat.title or "Premium Channel"
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Premium reward channel set to *{chat.title or 'Premium Channel'}*.",
        parse_mode="Markdown"
    )


# =========================================================
# COUPON ADMIN
# =========================================================

@bot.message_handler(
    commands=['coupon'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def create_coupon(message):

    parts = message.text.split()

    if len(parts) != 5:
        bot.reply_to(
            message,
            """Usage:
`/coupon CODE COINS MAX_USERS HOURS`

Example:
`/coupon WELCOME100 100 50 24`""",
            parse_mode="Markdown"
        )
        return

    try:

        code = parts[1].upper()
        coins = int(parts[2])
        max_users = int(parts[3])
        hours = int(parts[4])

        if coins < 0 or max_users <= 0 or hours <= 0:
            raise ValueError

        expires_at = datetime.now() + timedelta(hours=hours)

        coupons_col.update_one(
            {"code": code},
            {
                "$set": {
                    "code": code,
                    "coins": coins,
                    "max_uses": max_users,
                    "used_count": 0,
                    "expires_at": expires_at,
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )

        bot.reply_to(
            message,
            f"""✅ *Coupon Created!*

🎟 Code: `{code}`
🪙 Coins: {coins}
👥 Maximum Users: {max_users}
⏰ Expires in: {hours} hours""",
            parse_mode="Markdown"
        )

    except ValueError:
        bot.reply_to(
            message,
            "❌ Coins, maximum users and hours must be valid numbers."
        )


@bot.message_handler(
    commands=['coupons'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_coupons(message):

    coupons = list(
        coupons_col.find()
        .sort("created_at", DESCENDING)
        .limit(20)
    )

    if not coupons:
        bot.send_message(ADMIN_ID, "No coupons found.")
        return

    text = "🎟 *Recent Coupons*\n\n"

    for coupon in coupons:

        status = "⌛ Expired" if (
            coupon.get("expires_at")
            and coupon["expires_at"] < datetime.now()
        ) else "✅ Active"

        text += (
            f"`{coupon['code']}`\n"
            f"🪙 {coupon['coins']} coins | "
            f"👥 {coupon.get('used_count', 0)}/{coupon['max_uses']} used\n"
            f"{status}\n\n"
        )

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# FEEDBACK ADMIN
# =========================================================

@bot.message_handler(
    commands=['feedbacks'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def view_feedbacks(message):

    feedbacks = list(
        feedback_col.find()
        .sort("created_at", DESCENDING)
        .limit(20)
    )

    if not feedbacks:
        bot.send_message(ADMIN_ID, "💬 No feedback received yet.")
        return

    text = "💬 *Recent Feedback*\n\n"

    for index, feedback in enumerate(feedbacks, start=1):

        name = feedback.get("first_name") or "User"
        username = feedback.get("username")

        user_text = name
        if username:
            user_text += f" (@{username})"

        feedback_text = feedback.get("feedback", "")

        text += (
            f"*{index}. {user_text}*\n"
            f"📝 {feedback_text}\n\n"
        )

        if len(text) > 3500:
            bot.send_message(
                ADMIN_ID,
                text,
                parse_mode="Markdown"
            )
            text = ""

    if text:
        bot.send_message(
            ADMIN_ID,
            text,
            parse_mode="Markdown"
        )


# =========================================================
# BROADCAST
# =========================================================

@bot.message_handler(
    commands=['broadcast'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def broadcast_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """📢 Send the message you want to broadcast.

It will be sent to all users who have started the bot."""
    )

    bot.register_next_step_handler(
        msg,
        broadcast_message
    )


def broadcast_message(message):

    users = bot_users_col.find({}, {"user_id": 1})

    success = 0
    failed = 0

    bot.send_message(ADMIN_ID, "📢 Broadcasting started...")

    for user in users:

        try:
            bot.copy_message(
                user["user_id"],
                message.chat.id,
                message.message_id
            )

            success += 1
            time.sleep(0.04)

        except Exception:
            failed += 1

    bot.send_message(
        ADMIN_ID,
        f"""📢 *Broadcast Complete*

✅ Sent: {success}
❌ Failed: {failed}""",
        parse_mode="Markdown"
    )


# =========================================================
# BOT STATISTICS
# =========================================================

@bot.message_handler(
    commands=['stats'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def bot_stats(message):

    total_users = bot_users_col.count_documents({})

    verified_referrals = bot_users_col.count_documents(
        {"verified_referral": True}
    )

    total_coins_result = list(
        bot_users_col.aggregate([
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": "$coins"}
                }
            }
        ])
    )

    coins = (
        total_coins_result[0]["total"]
        if total_coins_result
        else 0
    )

    bot.send_message(
        ADMIN_ID,
        f"""📊 *Bot Statistics*

👥 Total Users: *{total_users}*
🔗 Verified Referrals: *{verified_referrals}*
🪙 Total User Coins: *{coins}*
📢 Paid Channels: *{channels_col.count_documents({})}*
🎁 Required Channels: *{force_channels_col.count_documents({})}*
💬 Feedback: *{feedback_col.count_documents({})}*""",
        parse_mode="Markdown"
    )


# =========================================================
# CLEAR EXPIRED PENDING PAYMENTS
# =========================================================

def clear_pending_payments():

    now = datetime.now()
    expired = []

    for user_id, data in list(pending_payments.items()):

        if (now - data["time"]).total_seconds() >= 600:

            try:
                bot.send_message(
                    user_id,
                    "⌛ Your payment verification request expired.\n\nPlease tap *I Have Paid* again.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

            expired.append(user_id)

    for user_id in expired:
        pending_payments.pop(user_id, None)


# =========================================================
# AUTO REMOVE EXPIRED USERS
# =========================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find(
        {"expiry": {"$lte": now}}
    )

    for user in expired_users:

        try:

            channel_id = user["channel_id"]
            user_id = user["user_id"]

            # Ban + unban removes user but allows them to rejoin later
            bot.ban_chat_member(
                channel_id,
                user_id
            )

            bot.unban_chat_member(
                channel_id,
                user_id
            )

            source = user.get(
                "source",
                "paid_subscription"
            )

            if source == "coin_reward":

                try:
                    bot.send_message(
                        user_id,
                        """⏰ *Your Premium Membership Has Expired*

Your redeemed Premium time has ended and you have been removed from the Premium channel.

🪙 Earn more coins through referrals and redeem Premium again!""",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            else:

                try:

                    bot_username = bot.get_me().username

                    rejoin_url = (
                        f"https://t.me/{bot_username}"
                        f"?start={channel_id}"
                    )

                    markup = InlineKeyboardMarkup()

                    markup.add(
                        InlineKeyboardButton(
                            "🔁 Re-Join / Renew",
                            url=rejoin_url
                        )
                    )

                    bot.send_message(
                        user_id,
                        "⚠️ Your subscription has expired.\n\nClick below to renew your subscription.",
                        reply_markup=markup
                    )

                except Exception as e:
                    print(f"Renew message error: {e}")

            # Only delete after successfully removing user
            users_col.delete_one(
                {"_id": user["_id"]}
            )

        except Exception as e:
            # Keep record so the scheduler retries
            print(f"Kick expired user error: {e}")


# =========================================================
# START BOT
# =========================================================

if __name__ == "__main__":

    keep_alive()

    # Create default settings
    get_settings()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        kick_expired_users,
        "interval",
        minutes=1,
        max_instances=1
    )

    scheduler.add_job(
        clear_pending_payments,
        "interval",
        minutes=1,
        max_instances=1
    )

    scheduler.start()

    bot.remove_webhook()

    try:

        print("✅ Bot is running...")

        bot.infinity_polling(
            timeout=20,
            long_polling_timeout=10
        )

    except Exception as e:
        print(f"Polling error: {e}")