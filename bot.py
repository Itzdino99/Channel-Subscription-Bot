import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
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
ADMIN_ID = int(os.getenv('ADMIN_ID'))
UPI_ID = os.getenv('UPI_ID')
CONTACT_USERNAME = os.getenv('CONTACT_USERNAME')

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client['sub_management']

channels_col = db['channels']
users_col = db['users']
settings_col = db['settings']
coupons_col = db['coupons']

pending_payments = {}


# =========================================================
# HELPERS
# =========================================================

def get_settings():
    settings = settings_col.find_one({"_id": "bot_settings"})

    if not settings:
        settings = {
            "_id": "bot_settings",
            "referral_reward": 10,
            "verify_groups": [],
            "reward_channel": None,
            "reward_coin_cost": 100,
            "reward_duration": 10080
        }
        settings_col.insert_one(settings)

    return settings


def get_user(user_id):
    user = users_col.find_one({"user_id": user_id})

    if not user:
        users_col.insert_one({
            "user_id": user_id,
            "coins": 0,
            "referral_count": 0,
            "referred_by": None,
            "referral_verified": False
        })

        user = users_col.find_one({"user_id": user_id})

    return user


def add_coins(user_id, amount):
    get_user(user_id)

    users_col.update_one(
        {"user_id": user_id},
        {"$inc": {"coins": amount}}
    )


def plan_label(minutes):
    minutes = int(minutes)

    if minutes > 525600:
        return "💎 Lifetime"
    elif minutes >= 1440:
        return f"📅 {minutes // 1440} Days"
    else:
        return f"⏱ {minutes} Minutes"


def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)

    markup.add(
        InlineKeyboardButton("🌑 My Balance", callback_data="my_balance"),
        InlineKeyboardButton("🔗 Refer & Earn", callback_data="refer_earn")
    )

    markup.add(
        InlineKeyboardButton("🎁 Redeem Premium", callback_data="redeem_premium"),
        InlineKeyboardButton("🎟️ Claim Coupon", callback_data="claim_coupon")
    )

    markup.add(
        InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard"),
        InlineKeyboardButton("👥 My Referrals", callback_data="my_referrals")
    )

    markup.add(
        InlineKeyboardButton("📖 How It Works", callback_data="how_it_works")
    )

    markup.add(
        InlineKeyboardButton(
            "📞 Contact Admin",
            url=f"https://t.me/{CONTACT_USERNAME}"
        )
    )

    return markup


# =========================================================
# START COMMAND
# =========================================================

@bot.message_handler(commands=['start'])
def start_handler(message):

    user_id = message.from_user.id
    get_user(user_id)

    text = message.text.split()

    # -----------------------------------------------------
    # REFERRAL DEEP LINK
    # Example: /start ref_123456
    # -----------------------------------------------------

    if len(text) > 1 and text[1].startswith("ref_"):

        try:
            referrer_id = int(text[1].replace("ref_", ""))

            if referrer_id != user_id:

                user = get_user(user_id)

                # Only save referral once
                if not user.get("referred_by"):

                    users_col.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "referred_by": referrer_id,
                                "referral_verified": False
                            }
                        }
                    )

        except Exception as e:
            print("Referral error:", e)

    # -----------------------------------------------------
    # PAID SUBSCRIPTION CHANNEL DEEP LINK
    # -----------------------------------------------------

    if len(text) > 1 and not text[1].startswith("ref_"):

        try:

            ch_id = int(text[1])

            ch_data = channels_col.find_one(
                {"channel_id": ch_id}
            )

            if ch_data:

                markup = InlineKeyboardMarkup()

                # Existing Demo Button
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
                            plan_label(int(p_time)),
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

                bot.send_message(
                    message.chat.id,
                    """📌 *Notice*

• Demo access is for testing only.
• Read all instructions before making a payment.""",
                    parse_mode="Markdown"
                )

                return

        except Exception as e:
            print("Start channel error:", e)

    # -----------------------------------------------------
    # ADMIN
    # -----------------------------------------------------

    if user_id == ADMIN_ID:

        bot.send_message(
            message.chat.id,
            """✅ *Admin Panel Active!*

📢 *Paid Channel Commands*
/add - Add/Edit Paid Channel
/channels - Manage Paid Channels

🎁 *Referral Premium*
/setreward - Set Referral Reward Channel

🔗 *Referral System*
/addverify - Add Required Verification Group
/verifygroups - View Verification Groups
/setrefreward - Change Referral Coin Reward

🎟️ *Coupon System*
/coupon - Create Coin Coupon
/coupons - View Active Coupons

📢 *Other*
/broadcast - Send Message to All Users

Use /start anytime to open the user menu.""",
            parse_mode="Markdown"
        )

    else:

        bot.send_message(
            message.chat.id,
            "✨ *Welcome!*\n\nChoose an option below.",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )


# =========================================================
# USER MENU COMMAND
# =========================================================

@bot.message_handler(commands=['menu'])
def menu_command(message):
    get_user(message.from_user.id)

    bot.send_message(
        message.chat.id,
        "🎛️ *Main Menu*\n\nChoose an option below:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )


# =========================================================
# EXISTING PAID CHANNEL MANAGEMENT
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
        "Your Managed Channels:" if count else
        "No channels found. Click below to add one.",
        reply_markup=markup
    )


@bot.message_handler(
    commands=['add'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Please ensure the bot is an Admin in your channel.\n\n"
        "Then FORWARD any message from that channel here."
    )

    bot.register_next_step_handler(msg, get_plans)


@bot.callback_query_handler(func=lambda call: call.data == "add_new")
def cb_add_new(call):

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

1440:99,43200:199

Example:
1440 = 1 Day
43200 = 30 Days"""
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
            "❌ Error: Message was not forwarded.\n\nUse /add again."
        )


def finalize_channel(message, ch_id, ch_name):

    try:

        raw_plans = message.text.split(",")
        plans_dict = {}

        for p in raw_plans:
            t, pr = p.strip().split(":")
            plans_dict[t.strip()] = pr.strip()

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
https://t.me/{bot_username}?start={ch_id}"""
        )

    except Exception as e:

        print(e)

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format.\n\nUse:\n1440:99,43200:199"
        )


# =========================================================
# PAYMENT FLOW - ORIGINAL SYSTEM
# =========================================================

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
            f"💎 *Plan:* {plan_label(mins)}\n\n"
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
            "✅ After payment, tap *I Have Paid*.\n"
            "📷 Then send your payment screenshot to the admin."
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

Once uploaded, it will be sent to the admin for verification.

⏳ Please upload it within 10 minutes.""",
        parse_mode="Markdown"
    )


# =========================================================
# PAYMENT WAITING HANDLERS
# =========================================================

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

📷 Screenshot forwarded above."""
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
            """✅ Screenshot Uploaded Successfully!

⏳ Status: Waiting for admin verification.

🔔 Your invite link will be sent automatically after approval."""
        )

        del pending_payments[user_id]

    except Exception as e:

        print("PHOTO ERROR:", e)


# =========================================================
# PAYMENT APPROVAL
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("app_")
)
def approve_now(call):

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
                    "expiry": expiry_datetime.timestamp()
                }
            },
            upsert=True
        )

        bot.send_message(
            u_id,
            f"""🎉 *Payment Approved!*

💎 *Plan:* {plan_label(mins)}

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
            f"❌ Error:\n{e}"
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
        parse_mode="Markdown"
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# =========================================================
# USER BALANCE
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data == "my_balance")
def my_balance(call):

    user = get_user(call.from_user.id)

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        f"""💰 *My Balance*

🪙 Coins: *{user.get('coins', 0)}*

Use your coins to redeem premium membership! 🎁""",
        parse_mode="Markdown"
    )


# =========================================================
# REFERRAL SYSTEM
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data == "refer_earn")
def refer_earn(call):

    settings = get_settings()
    username = bot.get_me().username

    referral_link = (
        f"https://t.me/{username}?start=ref_{call.from_user.id}"
    )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        f"""🔗 *Refer & Earn*

Invite your friends using your personal link:

`{referral_link}`

🪙 You earn *{settings.get('referral_reward', 10)} coins* for every valid referral.

⚠️ Your friend must join the required groups and verify their account before the reward is added.""",
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda call: call.data == "my_referrals")
def my_referrals(call):

    user = get_user(call.from_user.id)

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        f"""👥 *My Referrals*

✅ Successful Referrals: *{user.get('referral_count', 0)}*

Keep sharing your referral link to earn more coins! 🪙""",
        parse_mode="Markdown"
    )


# =========================================================
# REFERRAL VERIFICATION
# =========================================================

@bot.callback_query_handler(func=lambda call: call.data == "verify_referral")
def verify_referral(call):

    user_id = call.from_user.id
    settings = get_settings()

    user = get_user(user_id)

    if not user.get("referred_by"):

        bot.answer_callback_query(
            call.id,
            "You were not referred by anyone.",
            show_alert=True
        )

        return

    if user.get("referral_verified"):

        bot.answer_callback_query(
            call.id,
            "Your referral is already verified!",
            show_alert=True
        )

        return

    groups = settings.get("verify_groups", [])

    if not groups:

        bot.answer_callback_query(
            call.id,
            "No verification groups have been configured yet.",
            show_alert=True
        )

        return

    not_joined = []

    for group in groups:

        try:

            member = bot.get_chat_member(
                group["channel_id"],
                user_id
            )

            if member.status in ["left", "kicked"]:

                not_joined.append(group["name"])

        except Exception:

            not_joined.append(group["name"])

    if not_joined:

        markup = InlineKeyboardMarkup()

        for group in groups:

            if group.get("username"):

                markup.add(
                    InlineKeyboardButton(
                        f"📢 Join {group['name']}",
                        url=f"https://t.me/{group['username']}"
                    )
                )

        markup.add(
            InlineKeyboardButton(
                "✅ Verify Again",
                callback_data="verify_referral"
            )
        )

        bot.send_message(
            call.message.chat.id,
            "❌ Please join all required groups before verifying.",
            reply_markup=markup
        )

        return

    # Mark user verified
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"referral_verified": True}}
    )

    referrer_id = user["referred_by"]
    reward = settings.get("referral_reward", 10)

    add_coins(referrer_id, reward)

    users_col.update_one(
        {"user_id": referrer_id},
        {"$inc": {"referral_count": 1}}
    )

    bot.answer_callback_query(
        call.id,
        "Verification successful!"
    )

    bot.send_message(
        user_id,
        "✅ *Verification Successful!*\n\nYour referral has been confirmed.",
        parse_mode="Markdown"
    )

    try:

        bot.send_message(
            referrer_id,
            f"""🎉 *New Successful Referral!*

🪙 You received *{reward} coins*!

Keep inviting friends! 🔗""",
            parse_mode="Markdown"
        )

    except:
        pass


# =========================================================
# REDEEM PREMIUM - SEPARATE REWARD CHANNEL
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "redeem_premium"
)
def redeem_premium(call):

    settings = get_settings()
    reward_channel = settings.get("reward_channel")

    if not reward_channel:

        bot.answer_callback_query(
            call.id,
            "Premium rewards are not configured yet.",
            show_alert=True
        )

        return

    user = get_user(call.from_user.id)

    coin_cost = settings.get("reward_coin_cost", 100)
    duration = settings.get("reward_duration", 10080)

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🎁 Redeem Now",
            callback_data="confirm_redeem"
        )
    )

    bot.send_message(
        call.message.chat.id,
        f"""🎁 *Redeem Referral Premium*

📢 Channel: *{reward_channel['name']}*
⏳ Duration: *{duration // 1440} Days*
🪙 Cost: *{coin_cost} Coins*

💰 Your Balance: *{user.get('coins', 0)} Coins*

Do you want to redeem your premium?""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(
    func=lambda call: call.data == "confirm_redeem"
)
def confirm_redeem(call):

    user_id = call.from_user.id
    settings = get_settings()

    reward_channel = settings.get("reward_channel")

    if not reward_channel:

        bot.answer_callback_query(
            call.id,
            "Reward channel is not configured.",
            show_alert=True
        )

        return

    coin_cost = settings.get("reward_coin_cost", 100)
    duration = settings.get("reward_duration", 10080)

    user = get_user(user_id)

    if user.get("coins", 0) < coin_cost:

        bot.answer_callback_query(
            call.id,
            "❌ You don't have enough coins!",
            show_alert=True
        )

        return

    try:

        # Deduct coins
        users_col.update_one(
            {
                "user_id": user_id,
                "coins": {"$gte": coin_cost}
            },
            {
                "$inc": {"coins": -coin_cost}
            }
        )

        expiry_datetime = (
            datetime.now() + timedelta(minutes=duration)
        )

        link = bot.create_chat_invite_link(
            reward_channel["channel_id"],
            member_limit=1,
            expire_date=int(expiry_datetime.timestamp())
        )

        # Save expiry separately using the reward channel ID
        users_col.update_one(
            {
                "user_id": user_id,
                "channel_id": reward_channel["channel_id"]
            },
            {
                "$set": {
                    "expiry": expiry_datetime.timestamp(),
                    "membership_type": "referral_reward"
                }
            },
            upsert=True
        )

        bot.send_message(
            user_id,
            f"""🎉 *Premium Redeemed Successfully!*

🪙 *{coin_cost} coins* have been deducted.

⏳ Premium Duration: *{duration // 1440} Days*

🔗 *Your One-Time Invite Link:*
{link.invite_link}

⚠️ The link can only be used once.""",
            parse_mode="Markdown"
        )

        bot.answer_callback_query(
            call.id,
            "Premium redeemed successfully!"
        )

    except Exception as e:

        print("Redeem error:", e)

        # Refund if invite creation failed
        add_coins(user_id, coin_cost)

        bot.answer_callback_query(
            call.id,
            "❌ Something went wrong. Your coins were refunded.",
            show_alert=True
        )


# =========================================================
# COUPON SYSTEM - USER
# =========================================================

coupon_waiting = set()


@bot.callback_query_handler(
    func=lambda call: call.data == "claim_coupon"
)
def claim_coupon(call):

    coupon_waiting.add(call.from_user.id)

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        """🎟️ *Claim Coupon*

Please send your coupon code now.

Example: `WELCOME100`""",
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in coupon_waiting,
    content_types=['text']
)
def process_coupon(message):

    user_id = message.from_user.id
    coupon_waiting.discard(user_id)

    code = message.text.strip().upper()

    coupon = coupons_col.find_one(
        {"code": code}
    )

    if not coupon:

        bot.reply_to(
            message,
            "❌ Invalid coupon code."
        )

        return

    now = datetime.now()

    if coupon["expires_at"] <= now:

        bot.reply_to(
            message,
            "⌛ This coupon has expired."
        )

        return

    if user_id in coupon.get("used_by", []):

        bot.reply_to(
            message,
            "⚠️ You have already used this coupon."
        )

        return

    if coupon.get("used_count", 0) >= coupon["max_uses"]:

        bot.reply_to(
            message,
            "❌ This coupon has reached its usage limit."
        )

        return

    # Atomic update prevents most duplicate claims
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
            "❌ Coupon is no longer available."
        )

        return

    coins = coupon["coins"]

    add_coins(user_id, coins)

    user = get_user(user_id)

    bot.reply_to(
        message,
        f"""🎉 *Coupon Claimed Successfully!*

🪙 You received: *{coins} Coins*
💰 New Balance: *{user.get('coins', 0)} Coins*""",
        parse_mode="Markdown"
    )


# =========================================================
# LEADERBOARD
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "leaderboard"
)
def leaderboard(call):

    top_users = list(
        users_col.find(
            {"referral_count": {"$gt": 0}}
        )
        .sort("referral_count", -1)
        .limit(10)
    )

    text = "🏆 *Referral Leaderboard*\n\n"

    if not top_users:
        text += "No successful referrals yet."
    else:

        for i, user in enumerate(top_users, 1):

            text += (
                f"{i}. 👤 User `{user['user_id']}`"
                f" — *{user.get('referral_count', 0)} Referrals*\n"
            )

    bot.answer_callback_query(call.id)

    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# HOW IT WORKS
# =========================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "how_it_works"
)
def how_it_works(call):

    settings = get_settings()

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "🔗 Refer & Earn",
            callback_data="refer_earn"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "✅ Verify Referral",
            callback_data="verify_referral"
        )
    )

    bot.send_message(
        call.message.chat.id,
        f"""📖 *How It Works*

1️⃣ Share your referral link with friends.

2️⃣ Your friend starts the bot using your link.

3️⃣ Your friend joins the required verification groups.

4️⃣ They press *Verify Referral*.

5️⃣ You receive *{settings.get('referral_reward', 10)} coins* 🪙

6️⃣ Collect coins and redeem premium access! 🎁

🎟️ You can also earn coins using special coupon codes.""",
        reply_markup=markup,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN - SET REWARD CHANNEL
# =========================================================

@bot.message_handler(
    commands=['setreward'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_reward_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """🎁 *Set Referral Premium Channel*

Forward any message from the separate premium channel.

⚠️ Make sure the bot is an ADMIN in that channel.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        get_reward_channel
    )


def get_reward_channel(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the channel."
        )

        return

    ch_id = message.forward_from_chat.id
    ch_name = message.forward_from_chat.title

    msg = bot.send_message(
        ADMIN_ID,
        f"""✅ Channel: *{ch_name}*

Now enter:

`COINS,DURATION_IN_MINUTES`

Example:
`100,10080`

= 100 coins for 7 days premium.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        save_reward_channel,
        ch_id,
        ch_name
    )


def save_reward_channel(message, ch_id, ch_name):

    try:

        coins, duration = message.text.split(",")

        coins = int(coins.strip())
        duration = int(duration.strip())

        settings_col.update_one(
            {"_id": "bot_settings"},
            {
                "$set": {
                    "reward_channel": {
                        "channel_id": ch_id,
                        "name": ch_name
                    },
                    "reward_coin_cost": coins,
                    "reward_duration": duration
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            f"""✅ *Referral Premium Configured!*

📢 Channel: {ch_name}
🪙 Cost: {coins} Coins
⏳ Duration: {duration} Minutes""",
            parse_mode="Markdown"
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format. Use: `100,10080`",
            parse_mode="Markdown"
        )


# =========================================================
# ADMIN - VERIFICATION GROUPS
# =========================================================

@bot.message_handler(
    commands=['addverify'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_verify_group(message):

    msg = bot.send_message(
        ADMIN_ID,
        """📢 *Add Verification Group*

Forward a message from the group/channel that users must join.

⚠️ The bot should be added to the group so it can check membership.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        save_verify_group
    )


def save_verify_group(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the required group."
        )

        return

    chat = message.forward_from_chat

    group = {
        "channel_id": chat.id,
        "name": chat.title,
        "username": chat.username
    }

    settings = get_settings()
    groups = settings.get("verify_groups", [])

    # Prevent duplicates
    if any(g["channel_id"] == chat.id for g in groups):

        bot.send_message(
            ADMIN_ID,
            "⚠️ This group is already added."
        )

        return

    groups.append(group)

    settings_col.update_one(
        {"_id": "bot_settings"},
        {"$set": {"verify_groups": groups}}
    )

    bot.send_message(
        ADMIN_ID,
        f"✅ Verification group added: {chat.title}"
    )


@bot.message_handler(
    commands=['verifygroups'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def verify_groups(message):

    settings = get_settings()
    groups = settings.get("verify_groups", [])

    if not groups:

        bot.send_message(
            ADMIN_ID,
            "No verification groups added yet."
        )

        return

    text = "📢 *Verification Groups*\n\n"

    for group in groups:
        text += f"• {group['name']}\n"

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# ADMIN - REFERRAL REWARD
# =========================================================

@bot.message_handler(
    commands=['setrefreward'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def set_ref_reward(message):

    msg = bot.send_message(
        ADMIN_ID,
        "🪙 Send the number of coins for each successful referral."
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
            f"✅ Referral reward set to {coins} coins."
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Please enter a valid number."
        )


# =========================================================
# ADMIN - CREATE COUPON
# =========================================================

@bot.message_handler(
    commands=['coupon'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def create_coupon(message):

    msg = bot.send_message(
        ADMIN_ID,
        """🎟️ *Create Coin Coupon*

Send details in this format:

`CODE,COINS,MAX_USERS,EXPIRY_MINUTES`

Example:
`WELCOME100,100,50,1440`

This gives:
🪙 100 coins
👥 Maximum 50 users
⏳ Valid for 24 hours""",
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
        coins = int(coins.strip())
        max_users = int(max_users.strip())
        expiry = int(expiry.strip())

        if coupons_col.find_one({"code": code}):

            bot.send_message(
                ADMIN_ID,
                "❌ This coupon code already exists."
            )

            return

        coupons_col.insert_one({
            "code": code,
            "coins": coins,
            "max_uses": max_users,
            "used_count": 0,
            "used_by": [],
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(minutes=expiry)
        })

        bot.send_message(
            ADMIN_ID,
            f"""🎉 *Coupon Created Successfully!*

🎟️ Code: `{code}`
🪙 Coins: {coins}
👥 Maximum Users: {max_users}
⏳ Valid for: {expiry} Minutes""",
            parse_mode="Markdown"
        )

    except Exception as e:

        print(e)

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid format. Please use the format shown."
        )


@bot.message_handler(
    commands=['coupons'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_coupons(message):

    now = datetime.now()

    coupons = list(
        coupons_col.find(
            {"expires_at": {"$gt": now}}
        )
    )

    if not coupons:

        bot.send_message(
            ADMIN_ID,
            "No active coupons."
        )

        return

    text = "🎟️ *Active Coupons*\n\n"

    for coupon in coupons:

        text += (
            f"🎟️ `{coupon['code']}`\n"
            f"🪙 {coupon['coins']} Coins\n"
            f"👥 {coupon['used_count']}/{coupon['max_uses']} Used\n"
            f"⏳ Until: {coupon['expires_at'].strftime('%Y-%m-%d %H:%M')}\n\n"
        )

    bot.send_message(
        ADMIN_ID,
        text,
        parse_mode="Markdown"
    )


# =========================================================
# BROADCAST SYSTEM
# =========================================================

@bot.message_handler(
    commands=['broadcast'],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def broadcast_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        """📢 *Broadcast Message*

Send or forward the message you want to broadcast.

It can be text, photo, video, etc.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        send_broadcast
    )


def send_broadcast(message):

    users = users_col.distinct("user_id")

    success = 0
    failed = 0

    status = bot.send_message(
        ADMIN_ID,
        "📤 Broadcasting..."
    )

    for user_id in users:

        if user_id == ADMIN_ID:
            continue

        try:

            bot.copy_message(
                user_id,
                message.chat.id,
                message.message_id
            )

            success += 1

        except:
            failed += 1

    bot.edit_message_text(
        f"""📢 *Broadcast Completed!*

✅ Sent: {success}
❌ Failed: {failed}""",
        status.chat.id,
        status.message_id,
        parse_mode="Markdown"
    )


# =========================================================
# CLEAR PENDING PAYMENTS
# =========================================================

def clear_pending_payments():

    now = datetime.now()
    expired = []

    for user_id, data in pending_payments.items():

        if (now - data["time"]).total_seconds() >= 600:

            try:

                bot.send_message(
                    user_id,
                    "⌛ Your payment verification request expired.\n\n"
                    "Please tap *I Have Paid* again.",
                    parse_mode="Markdown"
                )

            except:
                pass

            expired.append(user_id)

    for user_id in expired:

        del pending_payments[user_id]


# =========================================================
# AUTO REMOVE EXPIRED USERS
# =========================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find(
        {
            "expiry": {"$lte": now},
            "channel_id": {"$exists": True}
        }
    )

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

            # Paid users get renewal link
            # Referral reward users get menu instead
            if user.get("membership_type") == "referral_reward":

                bot.send_message(
                    user["user_id"],
                    """⚠️ Your referral premium has expired.

🪙 Earn more coins through referrals and redeem premium again!""",
                    reply_markup=main_menu()
                )

            else:

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
                    "⚠️ Your subscription has expired.\n\n"
                    "Click below to renew your subscription.",
                    reply_markup=markup
                )

            users_col.delete_one(
                {"_id": user["_id"]}
            )

        except Exception as e:

            print("Kick error:", e)


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