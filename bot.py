import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# =========================================================
# WEB SERVER / KEEP ALIVE
# =========================================================

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running and healthy!"

def run_web():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    Thread(target=run_web, daemon=True).start()


# =========================================================
# CONFIGURATION
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
UPI_ID = os.getenv("UPI_ID")
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME")

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client["sub_management"]

# OLD COLLECTIONS - KEPT FOR YOUR ORIGINAL SYSTEM
channels_col = db["channels"]
users_col = db["users"]

# NEW COLLECTIONS
profiles_col = db["profiles"]
memberships_col = db["memberships"]
settings_col = db["settings"]
coupons_col = db["coupons"]
history_col = db["coin_history"]

pending_payments = {}
coupon_waiting = set()


# =========================================================
# HELPERS
# =========================================================

def get_settings():
    settings = settings_col.find_one({"_id": "bot_settings"})

    if not settings:
        settings = {
            "_id": "bot_settings",
            "referral_reward": 10,
            "daily_reward": 5,
            "verify_groups": [],
            "reward_channel": None,
            "rewards": []
        }

        settings_col.insert_one(settings)

    return settings


def get_profile(user_id):
    profile = profiles_col.find_one({"user_id": user_id})

    if not profile:
        profiles_col.insert_one({
            "user_id": user_id,
            "coins": 0,
            "referral_count": 0,
            "referred_by": None,
            "referral_verified": False,
            "created_at": datetime.now(),
            "last_checkin": None
        })

        profile = profiles_col.find_one({"user_id": user_id})

    return profile


def add_coins(user_id, amount, reason="Reward"):
    get_profile(user_id)

    profiles_col.update_one(
        {"user_id": user_id},
        {"$inc": {"coins": amount}}
    )

    history_col.insert_one({
        "user_id": user_id,
        "amount": amount,
        "reason": reason,
        "time": datetime.now()
    })


def remove_coins(user_id, amount, reason="Spent"):
    result = profiles_col.update_one(
        {
            "user_id": user_id,
            "coins": {"$gte": amount}
        },
        {
            "$inc": {"coins": -amount}
        }
    )

    if result.modified_count == 0:
        return False

    history_col.insert_one({
        "user_id": user_id,
        "amount": -amount,
        "reason": reason,
        "time": datetime.now()
    })

    return True


def plan_label(minutes):
    minutes = int(minutes)

    if minutes > 525600:
        return "💎 Lifetime"
    elif minutes >= 1440:
        return f"📅 {minutes // 1440} Days"
    else:
        return f"⏱ {minutes} Minutes"


def format_remaining(expiry):
    remaining = int(expiry - datetime.now().timestamp())

    if remaining <= 0:
        return "Expired"

    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    minutes = (remaining % 3600) // 60

    if days > 0:
        return f"{days} Days {hours} Hours"

    if hours > 0:
        return f"{hours} Hours {minutes} Minutes"

    return f"{minutes} Minutes"


def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton("👤 My Profile", callback_data="my_profile"),
        InlineKeyboardButton("🪙 My Balance", callback_data="my_balance")
    )

    markup.add(
        InlineKeyboardButton("🔗 Refer & Earn", callback_data="refer_earn"),
        InlineKeyboardButton("🎁 Redeem Premium", callback_data="redeem_premium")
    )

    markup.add(
        InlineKeyboardButton("🎯 Daily Check-in", callback_data="daily_checkin"),
        InlineKeyboardButton("🎟️ Claim Coupon", callback_data="claim_coupon")
    )

    markup.add(
        InlineKeyboardButton("📜 Coin History", callback_data="coin_history"),
        InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")
    )

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    return markup


# =========================================================
# AUTOMATIC REFERRAL JOIN SCREEN
# =========================================================

def send_verification_screen(chat_id, user_id):
    settings = get_settings()
    groups = settings.get("verify_groups", [])

    if not groups:
        bot.send_message(
            chat_id,
            "✨ Welcome!\n\nThe referral system is currently being configured.",
            reply_markup=main_menu()
        )
        return

    markup = InlineKeyboardMarkup()

    for group in groups:
        invite_link = group.get("invite_link")

        if invite_link:
            markup.add(
                InlineKeyboardButton(
                    f"📢 Join {group['name']}",
                    url=invite_link
                )
            )

    markup.add(
        InlineKeyboardButton(
            "✅ Verify & Continue",
            callback_data="verify_referral"
        )
    )

    bot.send_message(
        chat_id,
        """🎉 *Welcome!*

To complete your registration, please join all the channels/groups below.

After joining them, click:

✅ *Verify & Continue*

Once verified, the person who invited you will automatically receive their referral reward! 🪙""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# START COMMAND
# =========================================================

@bot.message_handler(commands=["start"])
def start_handler(message):
    user_id = message.from_user.id
    get_profile(user_id)

    text = message.text.split()

    # =====================================================
    # REFERRAL LINK
    # =====================================================

    if len(text) > 1 and text[1].startswith("ref_"):

        try:
            referrer_id = int(text[1].replace("ref_", ""))
            profile = get_profile(user_id)

            # Referral is accepted ONLY for first-time users
            if (
                referrer_id != user_id
                and not profile.get("referred_by")
                and not profile.get("referral_verified")
            ):
                profiles_col.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "referred_by": referrer_id,
                            "referral_verified": False
                        }
                    }
                )

                # AUTOMATICALLY SHOW JOIN GROUPS
                send_verification_screen(
                    message.chat.id,
                    user_id
                )
                return

            # Already referred but not verified
            if (
                profile.get("referred_by")
                and not profile.get("referral_verified")
            ):
                send_verification_screen(
                    message.chat.id,
                    user_id
                )
                return

        except Exception as e:
            print("Referral error:", e)

    # =====================================================
    # OLD PAID SUBSCRIPTION SYSTEM
    # =====================================================

    if len(text) > 1 and not text[1].startswith("ref_"):

        try:
            ch_id = int(text[1])
            ch_data = channels_col.find_one(
                {"channel_id": ch_id}
            )

            if ch_data:
                markup = InlineKeyboardMarkup()

                # YOUR EXISTING DEMO BUTTON
                rejoin_url = "https://t.me/+lSW2hYbgrUNkMzFl"

                markup.add(
                    InlineKeyboardButton(
                        "🔗 ᴅᴇᴍᴏ",
                        url=rejoin_url
                    )
                )

                for p_time, p_price in ch_data["plans"].items():
                    markup.add(
                        InlineKeyboardButton(
                            plan_label(p_time),
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
                    message.chat.id,
                    f"""✨ *Welcome!*

📢 *Channel:* `{ch_data['name']}`

Select a subscription plan below.""",
                    reply_markup=markup,
                    parse_mode="Markdown"
                )

                return

        except Exception as e:
            print("Channel start error:", e)

    # =====================================================
    # ADMIN PANEL
    # =====================================================

    if user_id == ADMIN_ID:

        bot.send_message(
            message.chat.id,
            """👑 *Admin Panel*

📢 *Paid Subscription System*
/add - Add Paid Channel
/channels - View Channels

🔗 *Referral System*
/addverify - Add Required Group
/verifygroups - View Required Groups
/setrefreward - Set Referral Coins

🎁 *Premium Rewards*
/setrewardchannel - Set Premium Channel
/addreward - Add 1/7/30 Day Reward
/rewards - View Rewards

🎟️ *Coupons*
/coupon - Create Coupon
/coupons - View Coupons

🎯 *Coins*
/setdaily - Set Daily Reward

📊 *Management*
/stats - Bot Statistics
/broadcast - Send Broadcast

Use /menu to view the user panel.""",
            parse_mode="Markdown"
        )

    else:

        bot.send_message(
            message.chat.id,
            "✨ *Welcome!*\n\nChoose an option below.",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )


@bot.message_handler(commands=["menu"])
def menu_command(message):
    get_profile(message.from_user.id)

    bot.send_message(
        message.chat.id,
        "🎛️ *Main Menu*",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# =========================================================
# OLD PAID CHANNEL MANAGEMENT
# =========================================================

@bot.message_handler(
    commands=["add"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Please ensure the bot is Admin in your channel.\n\n"
        "Forward any message from that channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


@bot.message_handler(
    commands=["channels"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_channels(message):

    markup = InlineKeyboardMarkup()

    channels = list(
        channels_col.find({"admin_id": ADMIN_ID})
    )

    for ch in channels:
        markup.add(
            InlineKeyboardButton(
                f"📢 {ch['name']}",
                callback_data=f"manage_{ch['channel_id']}"
            )
        )

    markup.add(
        InlineKeyboardButton(
            "➕ Add New Channel",
            callback_data="add_new"
        )
    )

    bot.send_message(
        ADMIN_ID,
        "📢 Your Managed Channels:",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda c: c.data == "add_new")
def add_new_channel(call):

    msg = bot.send_message(
        ADMIN_ID,
        "Forward a message from your channel."
    )

    bot.register_next_step_handler(msg, get_plans)


def get_plans(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from a channel."
        )
        return

    ch_id = message.forward_from_chat.id
    ch_name = message.forward_from_chat.title

    msg = bot.send_message(
        ADMIN_ID,
        """Enter plans:

1440:99,10080:299,43200:999

Format:
MINUTES:PRICE"""
    )

    bot.register_next_step_handler(
        msg,
        finalize_channel,
        ch_id,
        ch_name
    )


def finalize_channel(message, ch_id, ch_name):

    try:
        plans_dict = {}

        for p in message.text.split(","):
            minutes, price = p.strip().split(":")
            plans_dict[minutes.strip()] = price.strip()

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

        username = bot.get_me().username

        bot.send_message(
            ADMIN_ID,
            f"""✅ Channel Added!

🔗 Subscription Link:

https://t.me/{username}?start={ch_id}"""
        )

    except:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


# =========================================================
# ORIGINAL PAYMENT SYSTEM
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data.startswith("select_")
)
def user_pays(call):

    _, ch_id, mins = call.data.split("_")

    ch_data = channels_col.find_one(
        {"channel_id": int(ch_id)}
    )

    price = float(ch_data["plans"][mins])

    usd_price = price / 100
    inr_price = price / 2

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

    qr_url = "https://i.ibb.co/v4yw96tb/IMG-20260712-103503.jpg"

    bot.send_photo(
        call.message.chat.id,
        qr_url,
        caption=f"""📢 *{ch_data['name']}*

💎 Plan: *{plan_label(mins)}*

💰 NPR: {price:.0f}
🇺🇸 USD: ${usd_price:.2f}
🇮🇳 INR: ₹{inr_price:.2f}

━━━━━━━━━━━━━━

*Binance ID:*
`{UPI_ID}`

*USDT (BNB) Address:*
`0x5a854d50bfaefb616387cd47fb15f32f1a8cb5e2`

📷 After payment, tap *I Have Paid* and send your screenshot.""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("paid_")
)
def payment_screenshot_request(call):

    _, ch_id, mins = call.data.split("_")
    user_id = call.from_user.id

    if user_id in pending_payments:
        bot.answer_callback_query(
            call.id,
            "You already have a pending payment.",
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

    bot.send_message(
        user_id,
        "📷 Please send your payment screenshot as a PHOTO."
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=["text"]
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "📷 Please send the payment screenshot as a PHOTO."
    )


@bot.message_handler(content_types=["photo"])
def photo_handler(message):

    user_id = message.from_user.id

    if user_id not in pending_payments:
        return

    payment = pending_payments[user_id]

    bot.forward_message(
        ADMIN_ID,
        message.chat.id,
        message.message_id
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
        f"""🔔 PAYMENT VERIFICATION

👤 {message.from_user.first_name}
🆔 {user_id}

📢 {payment['channel_name']}
💰 NPR {payment['price']}

Select an action:""",
        reply_markup=markup
    )

    bot.send_message(
        user_id,
        "✅ Screenshot received! Please wait for admin verification."
    )

    del pending_payments[user_id]


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("app_")
)
def approve_now(call):

    _, user_id, ch_id, mins = call.data.split("_")

    user_id = int(user_id)
    ch_id = int(ch_id)
    mins = int(mins)

    try:
        expiry = datetime.now() + timedelta(minutes=mins)

        link = bot.create_chat_invite_link(
            ch_id,
            member_limit=1,
            expire_date=int(expiry.timestamp())
        )

        # OLD SYSTEM DATA
        users_col.update_one(
            {
                "user_id": user_id,
                "channel_id": ch_id
            },
            {
                "$set": {
                    "expiry": expiry.timestamp()
                }
            },
            upsert=True
        )

        bot.send_message(
            user_id,
            f"""🎉 *Payment Approved!*

💎 Plan: {plan_label(mins)}

🔗 Your Join Link:
{link.invite_link}

⚠️ This link can only be used once.""",
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
            f"❌ Error: {e}"
        )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("rej_")
)
def reject_payment(call):

    user_id = int(call.data.split("_")[1])

    bot.send_message(
        user_id,
        "❌ Your payment could not be verified. Please contact the admin."
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# REFERRAL VERIFICATION - AUTOMATIC
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "verify_referral"
)
def verify_referral(call):

    user_id = call.from_user.id
    profile = get_profile(user_id)
    settings = get_settings()

    if not profile.get("referred_by"):
        bot.answer_callback_query(
            call.id,
            "No referral is pending.",
            show_alert=True
        )
        return

    if profile.get("referral_verified"):
        bot.answer_callback_query(
            call.id,
            "Already verified!",
            show_alert=True
        )
        return

    missing = []

    for group in settings.get("verify_groups", []):

        try:
            member = bot.get_chat_member(
                group["channel_id"],
                user_id
            )

            if member.status in ["left", "kicked"]:
                missing.append(group["name"])

        except:
            missing.append(group["name"])

    if missing:
        bot.answer_callback_query(
            call.id,
            "❌ Please join all required groups first!",
            show_alert=True
        )
        return

    referrer_id = profile["referred_by"]
    reward = settings.get("referral_reward", 10)

    # Prevent duplicate verification
    result = profiles_col.update_one(
        {
            "user_id": user_id,
            "referral_verified": False
        },
        {
            "$set": {
                "referral_verified": True
            }
        }
    )

    if result.modified_count == 0:
        return

    # AUTOMATIC COINS TO REFERRER
    add_coins(
        referrer_id,
        reward,
        "Successful Referral"
    )

    profiles_col.update_one(
        {"user_id": referrer_id},
        {"$inc": {"referral_count": 1}}
    )

    bot.answer_callback_query(
        call.id,
        "Verified successfully!"
    )

    bot.send_message(
        user_id,
        """🎉 *Verification Successful!*

You can now use the bot normally.""",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

    try:
        bot.send_message(
            referrer_id,
            f"""🎉 *New Successful Referral!*

🪙 +{reward} Coins added to your balance!"""
        )
    except:
        pass


# =========================================================
# REFERRAL LINK
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "refer_earn"
)
def refer_earn(call):

    username = bot.get_me().username
    settings = get_settings()

    link = (
        f"https://t.me/{username}?start=ref_{call.from_user.id}"
    )

    bot.send_message(
        call.message.chat.id,
        f"""🔗 *Refer & Earn*

Share your personal link:

`{link}`

🪙 Earn *{settings.get('referral_reward', 10)} coins*
for every friend who joins and successfully verifies!""",
        parse_mode="Markdown"
    )


# =========================================================
# MULTIPLE PREMIUM REWARDS
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "redeem_premium"
)
def redeem_premium(call):

    settings = get_settings()
    reward_channel = settings.get("reward_channel")
    rewards = settings.get("rewards", [])

    if not reward_channel:
        bot.answer_callback_query(
            call.id,
            "Premium channel has not been configured yet.",
            show_alert=True
        )
        return

    if not rewards:
        bot.answer_callback_query(
            call.id,
            "No premium rewards are available yet.",
            show_alert=True
        )
        return

    profile = get_profile(call.from_user.id)

    markup = InlineKeyboardMarkup()

    for reward in rewards:
        markup.add(
            InlineKeyboardButton(
                f"{reward['name']} — 🪙 {reward['coins']}",
                callback_data=f"redeem_{reward['id']}"
            )
        )

    bot.send_message(
        call.message.chat.id,
        f"""🎁 *Redeem Premium*

💰 Your Balance: *{profile.get('coins', 0)} Coins*

Choose the premium reward you want:""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith("redeem_")
)
def process_redeem(call):

    reward_id = call.data.replace("redeem_", "")
    settings = get_settings()

    reward_channel = settings.get("reward_channel")
    rewards = settings.get("rewards", [])

    reward = next(
        (r for r in rewards if str(r["id"]) == reward_id),
        None
    )

    if not reward or not reward_channel:
        bot.answer_callback_query(
            call.id,
            "Reward not available.",
            show_alert=True
        )
        return

    user_id = call.from_user.id
    cost = int(reward["coins"])

    # ATOMIC COIN DEDUCTION
    if not remove_coins(
        user_id,
        cost,
        f"Redeemed {reward['name']}"
    ):
        bot.answer_callback_query(
            call.id,
            "❌ You don't have enough coins!",
            show_alert=True
        )
        return

    try:
        expiry = (
            datetime.now() +
            timedelta(minutes=int(reward["duration"]))
        )

        link = bot.create_chat_invite_link(
            reward_channel["channel_id"],
            member_limit=1,
            expire_date=int(expiry.timestamp())
        )

        memberships_col.update_one(
            {
                "user_id": user_id,
                "channel_id": reward_channel["channel_id"]
            },
            {
                "$set": {
                    "user_id": user_id,
                    "channel_id": reward_channel["channel_id"],
                    "expiry": expiry.timestamp(),
                    "type": "referral_reward",
                    "reward_name": reward["name"]
                }
            },
            upsert=True
        )

        bot.send_message(
            user_id,
            f"""🎉 *Premium Redeemed Successfully!*

🎁 Reward: *{reward['name']}*
🪙 Coins Used: *{cost}*

🔗 *Your One-Time Invite Link:*
{link.invite_link}

⚠️ This membership will automatically expire when the reward duration ends.""",
            parse_mode="Markdown"
        )

        bot.answer_callback_query(
            call.id,
            "Premium redeemed!"
        )

    except Exception as e:
        # REFUND IF TELEGRAM INVITE FAILS
        add_coins(
            user_id,
            cost,
            "Refund - Premium Error"
        )

        print("Redeem error:", e)

        bot.answer_callback_query(
            call.id,
            "❌ Error occurred. Coins refunded.",
            show_alert=True
        )


# =========================================================
# BALANCE / PROFILE
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "my_balance"
)
def my_balance(call):

    profile = get_profile(call.from_user.id)

    bot.send_message(
        call.message.chat.id,
        f"""🪙 *My Balance*

💰 Available Coins: *{profile.get('coins', 0)}*""",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda c: c.data == "my_profile"
)
def my_profile(call):

    user_id = call.from_user.id
    profile = get_profile(user_id)

    memberships = list(
        memberships_col.find({
            "user_id": user_id,
            "expiry": {"$gt": datetime.now().timestamp()}
        })
    )

    text = f"""👤 *My Profile*

🪙 Coins: *{profile.get('coins', 0)}*
👥 Successful Referrals: *{profile.get('referral_count', 0)}*

💎 *Premium Status*
"""

    if memberships:
        for membership in memberships:
            text += (
                f"\n✅ {membership.get('reward_name', 'Premium')}"
                f"\n⏳ {format_remaining(membership['expiry'])}\n"
            )
    else:
        text += "\n❌ No active referral premium"

    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# DAILY CHECK-IN
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "daily_checkin"
)
def daily_checkin(call):

    user_id = call.from_user.id
    profile = get_profile(user_id)
    settings = get_settings()

    last_checkin = profile.get("last_checkin")
    now = datetime.now()

    if last_checkin:
        elapsed = now - last_checkin

        if elapsed.total_seconds() < 86400:
            remaining = 86400 - int(elapsed.total_seconds())

            hours = remaining // 3600
            minutes = (remaining % 3600) // 60

            bot.answer_callback_query(
                call.id,
                f"Come back in {hours}h {minutes}m!",
                show_alert=True
            )
            return

    reward = settings.get("daily_reward", 5)

    profiles_col.update_one(
        {"user_id": user_id},
        {"$set": {"last_checkin": now}}
    )

    add_coins(
        user_id,
        reward,
        "Daily Check-in"
    )

    bot.answer_callback_query(
        call.id,
        f"+{reward} Coins!"
    )

    bot.send_message(
        user_id,
        f"""🎉 *Daily Reward Claimed!*

🪙 +{reward} Coins added!

⏰ Come back after 24 hours for another reward.""",
        parse_mode="Markdown"
    )


# =========================================================
# COIN HISTORY
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "coin_history"
)
def coin_history(call):

    history = list(
        history_col.find(
            {"user_id": call.from_user.id}
        )
        .sort("time", -1)
        .limit(10)
    )

    text = "📜 *Recent Coin History*\n\n"

    if not history:
        text += "No transactions yet."

    for item in history:
        symbol = "➕" if item["amount"] > 0 else "➖"

        text += (
            f"{symbol} *{abs(item['amount'])} Coins*\n"
            f"📌 {item['reason']}\n"
            f"🕒 {item['time'].strftime('%d %b %Y, %H:%M')}\n\n"
        )

    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# COUPON SYSTEM
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "claim_coupon"
)
def claim_coupon(call):

    coupon_waiting.add(call.from_user.id)

    bot.send_message(
        call.message.chat.id,
        "🎟️ Send your coupon code now:"
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in coupon_waiting,
    content_types=["text"]
)
def process_coupon(message):

    user_id = message.from_user.id
    coupon_waiting.discard(user_id)

    code = message.text.strip().upper()

    coupon = coupons_col.find_one({"code": code})

    if not coupon:
        bot.reply_to(message, "❌ Invalid coupon.")
        return

    if coupon["expires_at"] <= datetime.now():
        bot.reply_to(message, "⌛ This coupon has expired.")
        return

    # ATOMIC CLAIM
    result = coupons_col.update_one(
        {
            "_id": coupon["_id"],
            "used_by": {"$ne": user_id},
            "used_count": {"$lt": coupon["max_uses"]}
        },
        {
            "$addToSet": {"used_by": user_id},
            "$inc": {"used_count": 1}
        }
    )

    if result.modified_count == 0:
        bot.reply_to(
            message,
            "❌ Coupon unavailable or already used."
        )
        return

    add_coins(
        user_id,
        coupon["coins"],
        f"Coupon {code}"
    )

    bot.reply_to(
        message,
        f"🎉 Coupon claimed! 🪙 +{coupon['coins']} Coins"
    )


# =========================================================
# LEADERBOARD
# =========================================================

@bot.callback_query_handler(
    func=lambda c: c.data == "leaderboard"
)
def leaderboard(call):

    top = list(
        profiles_col.find(
            {"referral_count": {"$gt": 0}}
        )
        .sort("referral_count", -1)
        .limit(10)
    )

    text = "🏆 *Referral Leaderboard*\n\n"

    if not top:
        text += "No successful referrals yet."

    for i, user in enumerate(top, 1):
        text += (
            f"{i}. 👤 User `{user['user_id']}`"
            f" — {user.get('referral_count', 0)} referrals\n"
        )

    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN - ADD VERIFICATION GROUP
# =========================================================

@bot.message_handler(
    commands=["addverify"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_verify(message):

    msg = bot.send_message(
        ADMIN_ID,
        """📢 Forward a message from the required channel/group.

The bot must be an ADMIN there.

After forwarding, you will be asked for the join link."""
    )

    bot.register_next_step_handler(
        msg,
        get_verify_group
    )


def get_verify_group(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the group."
        )
        return

    chat = message.forward_from_chat

    msg = bot.send_message(
        ADMIN_ID,
        f"""✅ {chat.title}

Now send the invite link users should use to join.

Example:
https://t.me/example"""
    )

    bot.register_next_step_handler(
        msg,
        save_verify_group,
        chat.id,
        chat.title
    )


def save_verify_group(message, chat_id, chat_name):

    invite_link = message.text.strip()

    settings = get_settings()
    groups = settings.get("verify_groups", [])

    if any(g["channel_id"] == chat_id for g in groups):
        bot.send_message(
            ADMIN_ID,
            "⚠️ This group is already added."
        )
        return

    groups.append({
        "channel_id": chat_id,
        "name": chat_name,
        "invite_link": invite_link
    })

    settings_col.update_one(
        {"_id": "bot_settings"},
        {"$set": {"verify_groups": groups}}
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Required group added: {chat_name}"
    )


@bot.message_handler(
    commands=["verifygroups"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def view_verify_groups(message):

    groups = get_settings().get("verify_groups", [])

    if not groups:
        bot.send_message(
            ADMIN_ID,
            "No verification groups configured."
        )
        return

    text = "📢 *Required Groups*\n\n"

    for group in groups:
        text += f"• {group['name']}\n"

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN - SET REFERRAL REWARD
# =========================================================

@bot.message_handler(
    commands=["setrefreward"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_ref_reward(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Send coins per successful referral:"
    )

    bot.register_next_step_handler(
        msg,
        save_ref_reward
    )


def save_ref_reward(message):

    try:
        coins = int(message.text)

        settings_col.update_one(
            {"_id": "bot_settings"},
            {"$set": {"referral_reward": coins}},
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Referral reward: {coins} Coins"
        )

    except:
        bot.send_message(
            ADMIN_ID,
            "❌ Please enter a valid number."
        )


# =========================================================
# ADMIN - SET PREMIUM REWARD CHANNEL
# =========================================================

@bot.message_handler(
    commands=["setrewardchannel"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_reward_channel(message):

    msg = bot.send_message(
        ADMIN_ID,
        """🎁 Forward a message from your separate Referral Premium Channel.

⚠️ The bot MUST be an admin in that channel."""
    )

    bot.register_next_step_handler(
        msg,
        save_reward_channel
    )


def save_reward_channel(message):

    if not message.forward_from_chat:
        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the premium channel."
        )
        return

    chat = message.forward_from_chat

    settings_col.update_one(
        {"_id": "bot_settings"},
        {
            "$set": {
                "reward_channel": {
                    "channel_id": chat.id,
                    "name": chat.title
                }
            }
        },
        upsert=True
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Referral Premium Channel set to: {chat.title}"
    )


# =========================================================
# ADMIN - ADD MULTIPLE PREMIUM REWARDS
# =========================================================

@bot.message_handler(
    commands=["addreward"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_reward(message):

    msg = bot.send_message(
        ADMIN_ID,
        """🎁 *Add Premium Reward*

Send details in this format:

`NAME,COINS,DURATION_IN_MINUTES`

Examples:

`1 Day Premium,20,1440`
`7 Days Premium,100,10080`
`30 Days Premium,300,43200`

You can add as many reward options as you want.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        save_reward
    )


def save_reward(message):

    try:
        name, coins, duration = message.text.split(",")

        name = name.strip()
        coins = int(coins.strip())
        duration = int(duration.strip())

        settings = get_settings()
        rewards = settings.get("rewards", [])

        # Unique ID
        reward_id = str(
            int(datetime.now().timestamp() * 1000)
        )

        rewards.append({
            "id": reward_id,
            "name": name,
            "coins": coins,
            "duration": duration
        })

        settings_col.update_one(
            {"_id": "bot_settings"},
            {"$set": {"rewards": rewards}}
        )

        bot.send_message(
            ADMIN_ID,
            f"""✅ *Reward Added!*

🎁 {name}
🪙 Cost: {coins} Coins
⏳ Duration: {duration} Minutes""",
            parse_mode="Markdown"
        )

    except:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format. Please follow the example."
        )


@bot.message_handler(
    commands=["rewards"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def view_rewards(message):

    rewards = get_settings().get("rewards", [])

    if not rewards:
        bot.send_message(
            ADMIN_ID,
            "No premium rewards added yet."
        )
        return

    text = "🎁 *Premium Rewards*\n\n"

    for reward in rewards:
        text += (
            f"• {reward['name']}\n"
            f"🪙 {reward['coins']} Coins\n"
            f"⏳ {reward['duration']} Minutes\n\n"
        )

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN - DAILY REWARD
# =========================================================

@bot.message_handler(
    commands=["setdaily"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_daily(message):

    msg = bot.send_message(
        ADMIN_ID,
        "🎯 Send the number of coins for daily check-in:"
    )

    bot.register_next_step_handler(
        msg,
        save_daily
    )


def save_daily(message):

    try:
        coins = int(message.text)

        settings_col.update_one(
            {"_id": "bot_settings"},
            {"$set": {"daily_reward": coins}},
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Daily reward set to {coins} coins."
        )

    except:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid number."
        )


# =========================================================
# ADMIN - CREATE COUPON
# =========================================================

@bot.message_handler(
    commands=["coupon"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def create_coupon(message):

    msg = bot.send_message(
        ADMIN_ID,
        """🎟️ Send coupon details:

`CODE,COINS,MAX_USERS,EXPIRY_MINUTES`

Example:

`WELCOME100,100,50,1440`""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        save_coupon
    )


def save_coupon(message):

    try:
        code, coins, max_users, expiry = (
            message.text.strip().upper().split(",")
        )

        code = code.strip()
        coins = int(coins)
        max_users = int(max_users)
        expiry = int(expiry)

        coupons_col.update_one(
            {"code": code},
            {
                "$setOnInsert": {
                    "code": code,
                    "coins": coins,
                    "max_uses": max_users,
                    "used_count": 0,
                    "used_by": [],
                    "created_at": datetime.now(),
                    "expires_at": (
                        datetime.now() +
                        timedelta(minutes=expiry)
                    )
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"✅ Coupon {code} created successfully!"
        )

    except:
        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format."
        )


# =========================================================
# ADMIN STATISTICS
# =========================================================

@bot.message_handler(
    commands=["stats"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def stats(message):

    total_users = profiles_col.count_documents({})
    successful_referrals = profiles_col.aggregate([
        {"$group": {
            "_id": None,
            "total": {"$sum": "$referral_count"}
        }}
    ])

    referral_data = list(successful_referrals)
    referral_count = (
        referral_data[0]["total"]
        if referral_data else 0
    )

    active_premium = memberships_col.count_documents({
        "expiry": {"$gt": datetime.now().timestamp()}
    })

    today = datetime.now().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    new_today = profiles_col.count_documents({
        "created_at": {"$gte": today}
    })

    bot.send_message(
        ADMIN_ID,
        f"""📊 *Bot Statistics*

👤 Total Users: *{total_users}*
🆕 New Users Today: *{new_today}*
🔗 Successful Referrals: *{referral_count}*
💎 Active Reward Premium: *{active_premium}*""",
        parse_mode="Markdown"
    )


# =========================================================
# BROADCAST
# =========================================================

@bot.message_handler(
    commands=["broadcast"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def broadcast_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "📢 Send or forward the message you want to broadcast."
    )

    bot.register_next_step_handler(
        msg,
        send_broadcast
    )


def send_broadcast(message):

    users = profiles_col.distinct("user_id")

    sent = 0
    failed = 0

    status = bot.send_message(
        ADMIN_ID,
        "📤 Broadcasting..."
    )

    for user_id in users:
        try:
            bot.copy_message(
                user_id,
                message.chat.id,
                message.message_id
            )
            sent += 1
        except:
            failed += 1

    bot.edit_message_text(
        f"""📢 *Broadcast Completed!*

✅ Sent: {sent}
❌ Failed: {failed}""",
        status.chat.id,
        status.message_id,
        parse_mode="Markdown"
    )


# =========================================================
# AUTOMATIC EXPIRY REMINDER
# =========================================================

def send_expiry_reminders():

    now = datetime.now().timestamp()
    tomorrow = now + 86400

    memberships = memberships_col.find({
        "expiry": {
            "$gt": now,
            "$lte": tomorrow
        },
        "reminder_sent": {"$ne": True}
    })

    for membership in memberships:

        try:
            bot.send_message(
                membership["user_id"],
                f"""⚠️ *Premium Expiry Reminder*

Your premium membership will expire in approximately:

⏳ *{format_remaining(membership['expiry'])}*

Earn more coins and redeem premium again! 🪙""",
                parse_mode="Markdown"
            )

            memberships_col.update_one(
                {"_id": membership["_id"]},
                {"$set": {"reminder_sent": True}}
            )

        except:
            pass


# =========================================================
# AUTO REMOVE EXPIRED MEMBERS
# =========================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    # NEW REFERRAL PREMIUM MEMBERS
    expired_memberships = memberships_col.find({
        "expiry": {"$lte": now}
    })

    for membership in expired_memberships:

        try:
            bot.ban_chat_member(
                membership["channel_id"],
                membership["user_id"]
            )

            bot.unban_chat_member(
                membership["channel_id"],
                membership["user_id"]
            )

            bot.send_message(
                membership["user_id"],
                """⚠️ Your premium membership has expired.

🪙 Refer friends, collect coins and redeem premium again!""",
                reply_markup=main_menu()
            )

        except Exception as e:
            print("Premium kick error:", e)

        memberships_col.delete_one(
            {"_id": membership["_id"]}
        )

    # OLD PAID MEMBERSHIP SYSTEM
    expired_paid = users_col.find({
        "expiry": {"$lte": now},
        "channel_id": {"$exists": True}
    })

    bot_username = bot.get_me().username

    for user in expired_paid:

        try:
            bot.ban_chat_member(
                user["channel_id"],
                user["user_id"]
            )

            bot.unban_chat_member(
                user["channel_id"],
                user["user_id"]
            )

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
                "⚠️ Your subscription has expired.",
                reply_markup=markup
            )

        except Exception as e:
            print("Paid kick error:", e)

        users_col.delete_one(
            {"_id": user["_id"]}
        )


# =========================================================
# CLEAR PENDING PAYMENTS
# =========================================================

def clear_pending_payments():

    now = datetime.now()
    expired = []

    for user_id, data in list(pending_payments.items()):

        if (now - data["time"]).total_seconds() >= 600:
            expired.append(user_id)

    for user_id in expired:
        try:
            bot.send_message(
                user_id,
                "⌛ Payment request expired. Please try again."
            )
        except:
            pass

        pending_payments.pop(user_id, None)


# =========================================================
# START BOT
# =========================================================

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

    scheduler.add_job(
        send_expiry_reminders,
        "interval",
        minutes=30
    )

    scheduler.start()

    bot.remove_webhook()

    print("✅ Bot is running...")

    bot.infinity_polling(
        timeout=20,
        long_polling_timeout=10
    )