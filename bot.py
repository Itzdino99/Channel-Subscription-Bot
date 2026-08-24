import os
import random
from datetime import datetime, timedelta
from threading import Thread

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask


# ============================================================
# RENDER KEEP-ALIVE SERVER
# ============================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running and healthy!"


def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    Thread(target=run_web, daemon=True).start()


# ============================================================
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
UPI_ID = os.getenv("UPI_ID", "")
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME", "").replace("@", "")

REFERRAL_REWARD = 10
DAILY_CHECKIN_MIN = 2
DAILY_CHECKIN_MAX = 5

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client["sub_management"]

# OLD COLLECTIONS
channels_col = db["channels"]
users_col = db["users"]

# NEW COLLECTIONS
required_groups_col = db["required_groups"]
premium_channels_col = db["premium_channels"]
coupons_col = db["coupons"]
coin_history_col = db["coin_history"]

pending_payments = {}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def is_admin(user_id):
    return user_id == ADMIN_ID


def get_user(user_id):
    return users_col.find_one({"user_id": user_id})


def get_or_create_user(tg_user):
    user = users_col.find_one({"user_id": tg_user.id})

    if not user:
        users_col.insert_one({
            "user_id": tg_user.id,
            "name": tg_user.first_name or "User",
            "username": tg_user.username,
            "coins": 0,
            "verified": False,
            "created_at": datetime.now()
        })
        return users_col.find_one({"user_id": tg_user.id})

    users_col.update_one(
        {"user_id": tg_user.id},
        {
            "$set": {
                "name": tg_user.first_name or "User",
                "username": tg_user.username
            }
        }
    )

    return users_col.find_one({"user_id": tg_user.id})


def is_user_verified(user_id):
    user = get_user(user_id)
    return bool(user and user.get("verified", False))


def add_coins(user_id, amount, reason=""):
    users_col.update_one(
        {"user_id": user_id},
        {
            "$inc": {"coins": amount}
        },
        upsert=True
    )

    coin_history_col.insert_one({
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
        "date": datetime.now()
    })


def get_required_groups():
    return list(required_groups_col.find({"active": True}))


def check_user_joined(chat_id, user_id):
    """
    Checks whether a user has joined a required group/channel.
    Bot must normally be an administrator in private channels.
    """
    try:
        member = bot.get_chat_member(chat_id, user_id)
        status = member.status

        if status in ["member", "administrator", "creator", "owner"]:
            return True

        if status == "restricted":
            return getattr(member, "is_member", False)

        return False

    except Exception as e:
        print(f"MEMBERSHIP CHECK ERROR ({chat_id}): {e}")
        return False


def get_contact_markup():
    markup = InlineKeyboardMarkup()
    if CONTACT_USERNAME:
        markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )
    return markup


# ============================================================
# USER MAIN MENU
# ============================================================

def show_user_menu(chat_id, user_id):

    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton("👤 My Profile", callback_data="menu_profile"),
        InlineKeyboardButton("🌑 My Balance", callback_data="menu_balance")
    )

    markup.add(
        InlineKeyboardButton("🔗 Refer & Earn", callback_data="menu_refer"),
        InlineKeyboardButton("🎁 Redeem Premium", callback_data="menu_redeem")
    )

    markup.add(
        InlineKeyboardButton("🎯 Daily Check-in", callback_data="menu_daily"),
        InlineKeyboardButton("🎟️ Claim Coupon", callback_data="menu_coupon")
    )

    markup.add(
        InlineKeyboardButton("📜 Coin History", callback_data="menu_history"),
        InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard")
    )

    markup.add(
        InlineKeyboardButton("📞 Contact Admin", callback_data="menu_contact")
    )

    bot.send_message(
        chat_id,
        """✨ *Welcome!*

Choose an option below.""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# REQUIRED GROUP VERIFICATION
# ============================================================

def show_verification_screen(chat_id, user_id):

    groups = get_required_groups()

    # If no groups are configured, allow access
    if not groups:
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"verified": True, "verified_at": datetime.now()}}
        )
        show_user_menu(chat_id, user_id)
        return

    markup = InlineKeyboardMarkup()

    for group in groups:
        name = group.get("name", "Required Channel")
        link = group.get("link")

        if link:
            markup.add(
                InlineKeyboardButton(
                    f"📢 Join {name}",
                    url=link
                )
            )

    markup.add(
        InlineKeyboardButton(
            "✅ Verify & Continue",
            callback_data="verify_required_groups"
        )
    )

    bot.send_message(
        chat_id,
        """🎉 *Welcome!*

To complete your registration, please join *all the channels/groups* below.

After joining them, click:

✅ *Verify & Continue*

🎁 Once verified, the person who invited you can automatically receive their referral reward!""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data == "verify_required_groups"
)
def verify_required_groups(call):

    user_id = call.from_user.id
    chat_id = call.message.chat.id

    groups = get_required_groups()
    missing_groups = []

    for group in groups:

        group_id = group.get("chat_id")

        if not group_id:
            continue

        if not check_user_joined(group_id, user_id):
            missing_groups.append(
                group.get("name", "Required Group")
            )

    # USER HAS NOT JOINED ALL GROUPS
    if missing_groups:

        names = "\n".join(
            f"• {name}" for name in missing_groups
        )

        bot.answer_callback_query(
            call.id,
            "❌ Please join all required groups first!",
            show_alert=True
        )

        bot.send_message(
            chat_id,
            f"""❌ *Verification Failed*

You still need to join:

{names}

After joining, press *Verify & Continue* again.

⚠️ Make sure you joined using the correct Telegram account.""",
            parse_mode="Markdown"
        )
        return

    # ALREADY VERIFIED - DON'T GIVE REWARD AGAIN
    user = get_user(user_id)

    if user and user.get("verified"):
        bot.answer_callback_query(call.id, "You are already verified!")
        show_user_menu(chat_id, user_id)
        return

    # MARK VERIFIED ONLY HERE
    users_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "verified": True,
                "verified_at": datetime.now()
            }
        }
    )

    # REFERRAL REWARD
    user = get_user(user_id)

    if (
        user
        and user.get("referrer_id")
        and not user.get("referral_rewarded", False)
    ):

        referrer_id = user["referrer_id"]

        if referrer_id != user_id:

            referrer = get_user(referrer_id)

            if referrer:
                add_coins(
                    referrer_id,
                    REFERRAL_REWARD,
                    f"Successful referral: {user_id}"
                )

                users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "referral_rewarded": True,
                            "referral_rewarded_at": datetime.now()
                        }
                    }
                )

                try:
                    bot.send_message(
                        referrer_id,
                        f"""🎉 *Referral Successful!*

Your friend successfully completed registration!

🪙 *+{REFERRAL_REWARD} Coins* have been added to your balance.""",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

    bot.answer_callback_query(
        call.id,
        "✅ Verification successful!"
    )

    try:
        bot.edit_message_reply_markup(
            chat_id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass

    bot.send_message(
        chat_id,
        """🎉 *Verification Successful!*

Welcome! You now have access to all features.""",
        parse_mode="Markdown"
    )

    continue_after_verification(chat_id, user_id)


# ============================================================
# START HANDLER
# ============================================================

@bot.message_handler(commands=["start"])
def start_handler(message):

    user_id = message.from_user.id
    chat_id = message.chat.id
    args = message.text.split()

    # ADMIN
    if is_admin(user_id) and len(args) == 1:
        show_admin_menu(chat_id)
        return

    # CREATE USER - BUT NEVER VERIFY HERE
    user = get_or_create_user(message.from_user)
    is_new_user = user.get("created_at") and not user.get("verified")

    # --------------------------------------------------------
    # REFERRAL LINK: /start ref_USERID
    # Only save referral for users who don't already have one.
    # --------------------------------------------------------

    if len(args) > 1 and args[1].startswith("ref_"):

        try:
            referrer_id = int(args[1].replace("ref_", ""))

            current = get_user(user_id)

            if (
                referrer_id != user_id
                and not current.get("referrer_id")
                and not current.get("verified")
                and get_user(referrer_id)
            ):
                users_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"referrer_id": referrer_id}}
                )

        except Exception as e:
            print(f"REFERRAL START ERROR: {e}")

    # --------------------------------------------------------
    # OLD SUBSCRIPTION DEEP LINK
    # /start CHANNEL_ID
    # --------------------------------------------------------

    elif len(args) > 1:

        try:
            ch_id = int(args[1])

            if channels_col.find_one({"channel_id": ch_id}):

                users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "pending_subscription_channel": ch_id
                        }
                    }
                )

        except ValueError:
            pass
        except Exception as e:
            print(f"START CHANNEL ERROR: {e}")

    # --------------------------------------------------------
    # IMPORTANT FIX:
    # CHECK VERIFICATION EVERY SINGLE TIME
    # --------------------------------------------------------

    if not is_user_verified(user_id):
        show_verification_screen(chat_id, user_id)
        return

    continue_after_verification(chat_id, user_id)


def continue_after_verification(chat_id, user_id):

    user = get_user(user_id)

    pending_channel = (
        user.get("pending_subscription_channel")
        if user else None
    )

    # Continue old subscription system
    if pending_channel:

        ch_data = channels_col.find_one(
            {"channel_id": pending_channel}
        )

        if ch_data:
            show_subscription_plans(
                chat_id,
                pending_channel,
                ch_data
            )

            users_col.update_one(
                {"user_id": user_id},
                {
                    "$unset": {
                        "pending_subscription_channel": ""
                    }
                }
            )
            return

    show_user_menu(chat_id, user_id)


# ============================================================
# USER MENU CALLBACKS
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("menu_")
)
def user_menu_handler(call):

    user_id = call.from_user.id
    chat_id = call.message.chat.id
    action = call.data

    if not is_user_verified(user_id):
        bot.answer_callback_query(
            call.id,
            "Please complete verification first!",
            show_alert=True
        )
        show_verification_screen(chat_id, user_id)
        return

    user = get_user(user_id)

    # PROFILE
    if action == "menu_profile":

        username = (
            f"@{user.get('username')}"
            if user.get("username")
            else "Not set"
        )

        referral_count = users_col.count_documents({
            "referrer_id": user_id,
            "verified": True
        })

        bot.send_message(
            chat_id,
            f"""👤 *My Profile*

🆔 ID: `{user_id}`
👤 Name: {user.get('name', 'User')}
🌐 Username: {username}

👥 Successful Referrals: *{referral_count}*
🪙 Coins: *{user.get('coins', 0)}*""",
            parse_mode="Markdown"
        )

    # BALANCE
    elif action == "menu_balance":

        bot.send_message(
            chat_id,
            f"""🌑 *My Balance*

🪙 Available Coins: *{user.get('coins', 0)}*

Earn more coins through:
🔗 Referrals
🎯 Daily Check-in
🎟️ Coupon Codes""",
            parse_mode="Markdown"
        )

    # REFER
    elif action == "menu_refer":

        bot_username = bot.get_me().username
        referral_link = (
            f"https://t.me/{bot_username}?start=ref_{user_id}"
        )

        referral_count = users_col.count_documents({
            "referrer_id": user_id,
            "verified": True
        })

        bot.send_message(
            chat_id,
            f"""🔗 *Refer & Earn*

Invite your friends using your personal link:

`{referral_link}`

🎁 You receive *{REFERRAL_REWARD} coins* when a new user:
1️⃣ Starts the bot using your link
2️⃣ Joins all required groups
3️⃣ Successfully verifies

👥 Successful Referrals: *{referral_count}*""",
            parse_mode="Markdown"
        )

    # REDEEM
    elif action == "menu_redeem":
        show_redeem_menu(chat_id)

    # DAILY CHECK-IN
    elif action == "menu_daily":
        daily_checkin(call)

    # COUPON
    elif action == "menu_coupon":

        msg = bot.send_message(
            chat_id,
            """🎟️ *Claim Coupon*

Please send your coupon code.

Example: `WELCOME10`""",
            parse_mode="Markdown"
        )

        bot.register_next_step_handler(
            msg,
            process_coupon
        )

    # HISTORY
    elif action == "menu_history":
        show_coin_history(chat_id, user_id)

    # LEADERBOARD
    elif action == "menu_leaderboard":
        show_leaderboard(chat_id)

    # CONTACT
    elif action == "menu_contact":
        bot.send_message(
            chat_id,
            "📞 Contact the administrator for assistance.",
            reply_markup=get_contact_markup()
        )

    bot.answer_callback_query(call.id)


# ============================================================
# DAILY CHECK-IN
# ============================================================

def daily_checkin(call):

    user_id = call.from_user.id
    user = get_user(user_id)
    now = datetime.now()

    last = user.get("last_checkin")

    if last:
        if isinstance(last, datetime):
            last_date = last.date()
        else:
            last_date = datetime.fromtimestamp(last).date()

        if last_date == now.date():
            bot.answer_callback_query(
                call.id,
                "❌ You already claimed today's reward!",
                show_alert=True
            )
            return

    reward = random.randint(
        DAILY_CHECKIN_MIN,
        DAILY_CHECKIN_MAX
    )

    add_coins(
        user_id,
        reward,
        "Daily Check-in Reward"
    )

    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"last_checkin": now}}
    )

    bot.answer_callback_query(
        call.id,
        f"🎉 You received {reward} coins!",
        show_alert=True
    )


# ============================================================
# COUPON SYSTEM
# ============================================================

def process_coupon(message):

    user_id = message.from_user.id
    code = message.text.strip().upper()

    if not is_user_verified(user_id):
        bot.send_message(
            user_id,
            "❌ Please complete verification first."
        )
        return

    coupon = coupons_col.find_one({"code": code})

    if not coupon:
        bot.send_message(
            user_id,
            "❌ Invalid coupon code."
        )
        return

    now = datetime.now()

    if not coupon.get("active", True):
        bot.send_message(user_id, "❌ This coupon is no longer active.")
        return

    expiry = coupon.get("expiry")

    if expiry and expiry < now:
        bot.send_message(user_id, "⌛ This coupon has expired.")
        return

    used_count = coupon.get("used_count", 0)
    max_uses = coupon.get("max_uses", 1)

    if used_count >= max_uses:
        bot.send_message(user_id, "❌ This coupon has reached its usage limit.")
        return

    if user_id in coupon.get("used_by", []):
        bot.send_message(user_id, "⚠️ You have already used this coupon.")
        return

    coins = coupon.get("coins", 0)

    add_coins(
        user_id,
        coins,
        f"Coupon: {code}"
    )

    coupons_col.update_one(
        {"_id": coupon["_id"]},
        {
            "$inc": {"used_count": 1},
            "$addToSet": {"used_by": user_id}
        }
    )

    bot.send_message(
        user_id,
        f"""🎉 *Coupon Claimed Successfully!*

🎟️ Code: `{code}`
🪙 Reward: *+{coins} Coins*""",
        parse_mode="Markdown"
    )


# ============================================================
# COIN HISTORY
# ============================================================

def show_coin_history(chat_id, user_id):

    history = list(
        coin_history_col.find(
            {"user_id": user_id}
        ).sort("date", -1).limit(10)
    )

    if not history:
        bot.send_message(
            chat_id,
            "📜 No coin history yet."
        )
        return

    text = "📜 *Recent Coin History*\n\n"

    for item in history:
        amount = item.get("amount", 0)
        reason = item.get("reason", "Unknown")
        text += f"{'➕' if amount >= 0 else '➖'} *{amount}* — {reason}\n"

    bot.send_message(
        chat_id,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# LEADERBOARD
# ============================================================

def show_leaderboard(chat_id):

    top_users = list(
        users_col.find(
            {"verified": True}
        ).sort("coins", -1).limit(10)
    )

    if not top_users:
        bot.send_message(chat_id, "🏆 No users on the leaderboard yet.")
        return

    text = "🏆 *Coin Leaderboard*\n\n"

    medals = ["🥇", "🥈", "🥉"]

    for i, user in enumerate(top_users):

        prefix = medals[i] if i < 3 else f"{i + 1}."

        name = user.get("name", "User")
        coins = user.get("coins", 0)

        text += f"{prefix} {name} — *{coins} 🪙*\n"

    bot.send_message(
        chat_id,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# PREMIUM REDEMPTION SYSTEM
# ============================================================

def show_redeem_menu(chat_id):

    channels = list(
        premium_channels_col.find({"active": True})
    )

    if not channels:
        bot.send_message(
            chat_id,
            "🎁 Premium rewards are not available yet."
        )
        return

    markup = InlineKeyboardMarkup()

    for channel in channels:

        channel_id = channel["channel_id"]
        name = channel.get("name", "Premium")

        rewards = channel.get(
            "rewards",
            {
                "1440": 100,
                "10080": 500,
                "43200": 1500
            }
        )

        for minutes, coins in rewards.items():

            mins = int(minutes)

            if mins == 1440:
                label = f"🎁 1 Day — {coins} 🪙"
            elif mins == 10080:
                label = f"🎁 7 Days — {coins} 🪙"
            elif mins == 43200:
                label = f"🎁 30 Days — {coins} 🪙"
            else:
                label = f"🎁 {mins // 1440} Days — {coins} 🪙"

            markup.add(
                InlineKeyboardButton(
                    f"{name}: {label}",
                    callback_data=f"redeem_{channel_id}_{mins}"
                )
            )

    bot.send_message(
        chat_id,
        """🎁 *Redeem Premium*

Use your earned coins to get Premium access!

Choose your reward:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("redeem_")
)
def redeem_premium(call):

    try:

        _, channel_id, mins = call.data.split("_")

        channel_id = int(channel_id)
        mins = int(mins)
        user_id = call.from_user.id

        channel = premium_channels_col.find_one(
            {
                "channel_id": channel_id,
                "active": True
            }
        )

        if not channel:
            bot.answer_callback_query(
                call.id,
                "Premium channel is unavailable.",
                show_alert=True
            )
            return

        rewards = channel.get("rewards", {})
        cost = rewards.get(str(mins))

        if cost is None:
            bot.answer_callback_query(
                call.id,
                "This reward is unavailable.",
                show_alert=True
            )
            return

        user = get_user(user_id)

        if user.get("coins", 0) < cost:
            bot.answer_callback_query(
                call.id,
                f"❌ You need {cost} coins!",
                show_alert=True
            )
            return

        # Deduct coins
        add_coins(
            user_id,
            -cost,
            f"Redeemed {mins} minute Premium"
        )

        expiry_datetime = datetime.now() + timedelta(
            minutes=mins
        )

        # Telegram invite link
        link = bot.create_chat_invite_link(
            channel_id,
            member_limit=1,
            expire_date=int(
                (datetime.now() + timedelta(days=1)).timestamp()
            )
        )

        # Save expiry for automatic kick
        users_col.update_one(
            {
                "user_id": user_id,
                "channel_id": channel_id
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp(),
                    "premium_reward": True
                }
            },
            upsert=True
        )

        if mins >= 1440:
            duration = f"{mins // 1440} Day(s)"
        else:
            duration = f"{mins} Minutes"

        bot.send_message(
            user_id,
            f"""🎉 *Premium Redeemed Successfully!*

💎 Duration: *{duration}*
🪙 Coins Used: *{cost}*

🔗 *Your Premium Link:*
{link.invite_link}

⚠️ This link can only be used once.""",
            parse_mode="Markdown"
        )

        bot.answer_callback_query(
            call.id,
            "🎉 Premium redeemed successfully!"
        )

    except Exception as e:
        print(f"REDEEM ERROR: {e}")

        bot.answer_callback_query(
            call.id,
            "❌ Something went wrong. Please contact admin.",
            show_alert=True
        )


# ============================================================
# OLD ADMIN CHANNEL SYSTEM
# ============================================================

@bot.message_handler(
    commands=["channels"],
    func=lambda m: is_admin(m.from_user.id)
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
        "Your Managed Channels:" if count else "No channels found.",
        reply_markup=markup
    )


@bot.message_handler(
    commands=["add"],
    func=lambda m: is_admin(m.from_user.id)
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """Please ensure the bot is an Admin in your channel.

Then FORWARD any message from that channel here."""
    )

    bot.register_next_step_handler(msg, get_plans)


@bot.callback_query_handler(
    func=lambda call: call.data == "add_new"
)
def cb_add_new(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        "Please FORWARD any message from your channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


def get_plans(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Message was not forwarded. Use /add again."
        )
        return

    ch_id = message.forward_from_chat.id
    ch_name = message.forward_from_chat.title

    msg = bot.send_message(
        ADMIN_ID,
        f"""✅ Channel Detected: {ch_name}

Enter plans like:

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


def finalize_channel(message, ch_id, ch_name):

    try:

        raw_plans = message.text.split(",")
        plans_dict = {}

        for p in raw_plans:
            t, price = p.strip().split(":")
            plans_dict[t.strip()] = price.strip()

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
            "❌ Invalid format. Example: `1440:99,43200:199`",
            parse_mode="Markdown"
        )


# ============================================================
# OLD SUBSCRIPTION PLANS
# ============================================================

def show_subscription_plans(chat_id, ch_id, ch_data):

    markup = InlineKeyboardMarkup()

    rejoin_url = "https://t.me/+lSW2hYbgrUNkMzFl"

    markup.add(
        InlineKeyboardButton(
            "🔗 ᴅᴇᴍᴏ",
            url=rejoin_url
        )
    )

    for p_time in ch_data["plans"]:

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
                callback_data=f"select_{ch_id}_{p_time}"
            )
        )

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    bot.send_message(
        chat_id,
        f"""✨ *Welcome!*

📢 *Channel:* `{ch_data['name']}`

Select a subscription plan below.""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ============================================================
# OLD PAYMENT FLOW
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("select_")
)
def user_pays(call):

    _, ch_id, mins = call.data.split("_")

    ch_data = channels_col.find_one(
        {"channel_id": int(ch_id)}
    )

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
            "*USDT (BNB) Address:*\n"
            "`0x5a854d50bfaefb616387cd47fb15f32f1a8cb5e2`\n\n"
            "📋 Tap the payment details to copy them.\n\n"
            "✅ After payment, tap *I Have Paid*."
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
            "⚠️ You already have a pending payment.",
            show_alert=True
        )
        return

    ch_data = channels_col.find_one(
        {"channel_id": int(ch_id)}
    )

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

⏳ Upload it within 10 minutes.""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=["text"]
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "📷 Please upload your payment screenshot as a PHOTO."
    )


@bot.message_handler(content_types=["document"])
def document_handler(message):

    if message.from_user.id not in pending_payments:
        return

    bot.reply_to(
        message,
        "❌ Please send the screenshot as a PHOTO, not as a document."
    )


@bot.message_handler(content_types=["photo"])
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
💰 Price: NPR {payment['price']}"""
        )

        markup = InlineKeyboardMarkup(row_width=2)

        markup.add(
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=(
                    f"app_{user_id}_{payment['channel_id']}_{payment['plan']}"
                )
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
            """✅ *Screenshot Uploaded Successfully!*

⏳ Status: Waiting for admin verification.

Once approved, your invite link will be sent automatically.""",
            reply_markup=get_contact_markup(),
            parse_mode="Markdown"
        )

        del pending_payments[user_id]

    except Exception as e:
        print(f"PHOTO ERROR: {e}")


# ============================================================
# PAYMENT APPROVAL
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("app_")
)
def approve_now(call):

    _, u_id, ch_id, mins = call.data.split("_")

    u_id = int(u_id)
    ch_id = int(ch_id)
    mins = int(mins)

    try:

        expiry_datetime = datetime.now() + timedelta(
            minutes=mins
        )

        link = bot.create_chat_invite_link(
            ch_id,
            member_limit=1,
            expire_date=int(
                (datetime.now() + timedelta(days=1)).timestamp()
            )
        )

        users_col.update_one(
            {
                "user_id": u_id,
                "channel_id": ch_id
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp()
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
        bot.send_message(
            ADMIN_ID,
            f"❌ Approval Error:\n{e}"
        )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("rej_")
)
def reject_payment(call):

    user_id = int(call.data.split("_")[1])

    bot.send_message(
        user_id,
        """❌ *Payment Rejected*

Your payment could not be verified.

Please contact the admin if you believe this is a mistake.""",
        parse_mode="Markdown",
        reply_markup=get_contact_markup()
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# ============================================================
# ADMIN PANEL
# ============================================================

def show_admin_menu(chat_id):

    bot.send_message(
        chat_id,
        """👑 *ADMIN PANEL*

📢 *Old Subscription System*
/add - Add subscription channel
/channels - View subscription channels

👥 *Required Verification*
/addgroup - Add required group/channel
/groups - View required groups

💎 *Premium Rewards*
/addpremium - Add premium reward channel
/premiumchannels - View premium channels

🎟️ *Coupons*
/coupon - Create coin coupon

📢 *Broadcast*
/broadcast - Send message to all verified users

📊 /stats - Bot statistics

⚠️ The bot must be an administrator in channels it needs to manage.""",
        parse_mode="Markdown"
    )


# ============================================================
# ADD REQUIRED GROUP
# ============================================================

@bot.message_handler(
    commands=["addgroup"],
    func=lambda m: is_admin(m.from_user.id)
)
def add_required_group(message):

    msg = bot.send_message(
        ADMIN_ID,
        """📢 Forward any message from the group/channel you want users to join.

⚠️ Make sure the bot is an administrator there."""
    )

    bot.register_next_step_handler(
        msg,
        get_required_group
    )


def get_required_group(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the group/channel."
        )
        return

    chat = message.forward_from_chat

    msg = bot.send_message(
        ADMIN_ID,
        f"""✅ Detected: {chat.title}

Now send the group's public link or invite link.

Example:
https://t.me/example"""
    )

    bot.register_next_step_handler(
        msg,
        save_required_group,
        chat.id,
        chat.title
    )


def save_required_group(message, chat_id, name):

    link = message.text.strip()

    required_groups_col.update_one(
        {"chat_id": chat_id},
        {
            "$set": {
                "chat_id": chat_id,
                "name": name,
                "link": link,
                "active": True
            }
        },
        upsert=True
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ {name} added as a required group!"
    )


@bot.message_handler(
    commands=["groups"],
    func=lambda m: is_admin(m.from_user.id)
)
def list_required_groups(message):

    groups = get_required_groups()

    if not groups:
        bot.send_message(ADMIN_ID, "No required groups added.")
        return

    text = "👥 *Required Groups*\n\n"

    for group in groups:
        text += f"• {group.get('name')}\n"

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# ADD PREMIUM REWARD CHANNEL
# ============================================================

@bot.message_handler(
    commands=["addpremium"],
    func=lambda m: is_admin(m.from_user.id)
)
def add_premium_channel(message):

    msg = bot.send_message(
        ADMIN_ID,
        """💎 Forward any message from your PREMIUM channel.

⚠️ The bot must be an administrator."""
    )

    bot.register_next_step_handler(
        msg,
        get_premium_channel
    )


def get_premium_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the premium channel."
        )
        return

    chat = message.forward_from_chat

    msg = bot.send_message(
        ADMIN_ID,
        f"""✅ Premium Channel: {chat.title}

Set rewards in this format:

`1440:100,10080:500,43200:1500`

Meaning:
• 1 Day = 100 coins
• 7 Days = 500 coins
• 30 Days = 1500 coins""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        save_premium_channel,
        chat.id,
        chat.title
    )


def save_premium_channel(message, chat_id, name):

    try:

        rewards = {}

        for item in message.text.split(","):
            minutes, cost = item.strip().split(":")
            rewards[minutes.strip()] = int(cost.strip())

        premium_channels_col.update_one(
            {"channel_id": chat_id},
            {
                "$set": {
                    "channel_id": chat_id,
                    "name": name,
                    "rewards": rewards,
                    "active": True
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            "✅ Premium reward channel added successfully!"
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format. Try again using:\n1440:100,10080:500,43200:1500"
        )


@bot.message_handler(
    commands=["premiumchannels"],
    func=lambda m: is_admin(m.from_user.id)
)
def list_premium_channels(message):

    channels = list(premium_channels_col.find({"active": True}))

    if not channels:
        bot.send_message(ADMIN_ID, "No premium channels added.")
        return

    text = "💎 *Premium Channels*\n\n"

    for channel in channels:
        text += f"• {channel.get('name')}\n"

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# ============================================================
# CREATE COUPON
# ============================================================

@bot.message_handler(
    commands=["coupon"],
    func=lambda m: is_admin(m.from_user.id)
)
def create_coupon_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """🎟️ Send coupon details in this format:

`CODE:COINS:MAX_USERS:HOURS`

Example:
`WELCOME10:10:100:24`

This gives 10 coins to maximum 100 users and expires after 24 hours.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        create_coupon
    )


def create_coupon(message):

    try:

        code, coins, max_users, hours = (
            message.text.strip().upper().split(":")
        )

        coupons_col.update_one(
            {"code": code},
            {
                "$set": {
                    "code": code,
                    "coins": int(coins),
                    "max_uses": int(max_users),
                    "used_count": 0,
                    "used_by": [],
                    "expiry": datetime.now() + timedelta(
                        hours=int(hours)
                    ),
                    "active": True,
                    "created_at": datetime.now()
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"""✅ *Coupon Created!*

🎟️ Code: `{code}`
🪙 Coins: {coins}
👥 Maximum Users: {max_users}
⌛ Valid: {hours} hours""",
            parse_mode="Markdown"
        )

    except Exception:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


# ============================================================
# BROADCAST SYSTEM
# ============================================================

@bot.message_handler(
    commands=["broadcast"],
    func=lambda m: is_admin(m.from_user.id)
)
def broadcast_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """📢 Send the message you want to broadcast.

It will be sent to all verified users."""
    )

    bot.register_next_step_handler(
        msg,
        send_broadcast
    )


def send_broadcast(message):

    users = users_col.find({"verified": True})

    success = 0
    failed = 0

    bot.send_message(
        ADMIN_ID,
        "📤 Broadcast started..."
    )

    for user in users:

        try:
            bot.copy_message(
                user["user_id"],
                message.chat.id,
                message.message_id
            )
            success += 1

        except Exception:
            failed += 1

    bot.send_message(
        ADMIN_ID,
        f"""📢 *Broadcast Completed*

✅ Sent: {success}
❌ Failed: {failed}""",
        parse_mode="Markdown"
    )


# ============================================================
# BOT STATISTICS
# ============================================================

@bot.message_handler(
    commands=["stats"],
    func=lambda m: is_admin(m.from_user.id)
)
def show_stats(message):

    total = users_col.count_documents(
        {"channel_id": {"$exists": False}}
    )

    verified = users_col.count_documents(
        {"verified": True}
    )

    bot.send_message(
        ADMIN_ID,
        f"""📊 *Bot Statistics*

👥 Total Users: {total}
✅ Verified Users: {verified}
📢 Subscription Channels: {channels_col.count_documents({})}
💎 Premium Channels: {premium_channels_col.count_documents({"active": True})}""",
        parse_mode="Markdown"
    )


# ============================================================
# CLEAR PENDING PAYMENTS
# ============================================================

def clear_pending_payments():

    now = datetime.now()
    expired = []

    for user_id, data in list(pending_payments.items()):

        if (now - data["time"]).total_seconds() >= 600:

            try:
                bot.send_message(
                    user_id,
                    """⌛ Your payment verification request expired.

Please tap *I Have Paid* again and upload your screenshot.""",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

            expired.append(user_id)

    for user_id in expired:
        pending_payments.pop(user_id, None)


# ============================================================
# AUTO REMOVE EXPIRED USERS
# ============================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find({
        "expiry": {"$lte": now},
        "channel_id": {"$exists": True}
    })

    bot_username = bot.get_me().username

    for user in expired_users:

        try:

            bot.ban_chat_member(
                user["channel_id"],
                user["user_id"]
            )

            bot.unban_chat_member(
                user["channel_id"],
                user["user_id"]
            )

            # Only old paid subscriptions have a renewal link
            channel_data = channels_col.find_one({
                "channel_id": user["channel_id"]
            })

            if channel_data:

                rejoin_url = (
                    f"https://t.me/{bot_username}"
                    f"?start={user['channel_id']}"
                )

                markup = InlineKeyboardMarkup()

                markup.add(
                    InlineKeyboardButton(
                        "🔁 Re-Join / Renew",
                        url=rejoin_url
                    )
                )

                bot.send_message(
                    user["user_id"],
                    """⚠️ Your subscription has expired.

Click below to renew your subscription.""",
                    reply_markup=markup
                )

            else:
                bot.send_message(
                    user["user_id"],
                    """⌛ Your Premium reward has expired.

You can earn more coins and redeem Premium again!"""
                )

            users_col.delete_one(
                {"_id": user["_id"]}
            )

        except Exception as e:
            print(f"KICK ERROR: {e}")


# ============================================================
# START BOT
# ============================================================

if __name__ == "__main__":

    keep_alive()

    scheduler = BackgroundScheduler()

    scheduler.add_job(
        kick_expired_users,
        "interval",
        minutes=1
    )

    scheduler.add_job(
        clear_pending_payments,
        "interval",
        minutes=1
    )

    scheduler.start()

    bot.remove_webhook()

    print("✅ Bot is running...")

    try:
        bot.infinity_polling(
            timeout=20,
            long_polling_timeout=10
        )
    except Exception as e:
        print(f"Polling error: {e}")