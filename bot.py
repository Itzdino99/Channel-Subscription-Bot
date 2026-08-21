import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask
from threading import Thread

# ============================================================
# RENDER KEEP-ALIVE
# ============================================================

app = Flask("")

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
ADMIN_ID = int(os.getenv("ADMIN_ID"))
UPI_ID = os.getenv("UPI_ID")
CONTACT_USERNAME = os.getenv("CONTACT_USERNAME")

bot = telebot.TeleBot(BOT_TOKEN)

client = MongoClient(MONGO_URI)
db = client["sub_management"]

channels_col = db["channels"]
users_col = db["users"]

# NEW COLLECTIONS
competitions_col = db["competitions"]
competition_scores_col = db["competition_scores"]


# ============================================================
# TEMP PAYMENT STORAGE
# ============================================================

pending_payments = {}


# ============================================================
# HELPER: PLAN NAME
# ============================================================

def get_plan_name(minutes):

    minutes = int(minutes)

    if minutes > 525600:
        return "💎 Lifetime"

    elif minutes >= 1440:
        return f"📅 {minutes // 1440} Days"

    else:
        return f"⏱ {minutes} Minutes"


# ============================================================
# USER START
# ============================================================

@bot.message_handler(commands=["start"])
def start_handler(message):

    user_id = message.from_user.id
    text = message.text.split()

    # --------------------------------------------------------
    # PAID CHANNEL DEEP LINK
    # --------------------------------------------------------

    if len(text) > 1:

        try:

            ch_id = int(text[1])

            ch_data = channels_col.find_one({
                "channel_id": ch_id
            })

            if ch_data:

                markup = InlineKeyboardMarkup()

                rejoin_url = "https://t.me/+lSW2hYbgrUNkMzFl"

                markup.add(
                    InlineKeyboardButton(
                        "🔗 ᴅᴇᴍᴏ",
                        url=rejoin_url
                    )
                )

                USD_RATE = 100
                INR_RATE = 2

                for p_time, p_price in ch_data["plans"].items():

                    minutes = int(p_time)

                    label = get_plan_name(minutes)

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
                    message.chat.id,
                    f"""✨ *Welcome!*

📢 *Channel:* `{ch_data['name']}`

Select a subscription plan below.
""",
                    reply_markup=markup,
                    parse_mode="Markdown"
                )

                bot.send_message(
                    message.chat.id,
                    """📌 *Notice*

• Demo access is for testing only.
• Read all instructions before making a payment.
""",
                    parse_mode="Markdown"
                )

                return

        except Exception as e:
            print("START ERROR:", e)


    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if user_id == ADMIN_ID:

        bot.send_message(
            message.chat.id,
            "✅ Admin Panel Active!\n\n"
            "/add - Add/Edit Channel & Prices\n"
            "/channels - Manage Existing Channels\n"
            "/competition - Competition Settings"
        )

    else:

        bot.send_message(
            message.chat.id,
            "Welcome! To join a channel, please use the link provided by the Admin."
        )


# ============================================================
# CHANNEL MANAGEMENT
# ============================================================

@bot.message_handler(
    commands=["channels"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def list_channels(message):

    markup = InlineKeyboardMarkup()

    cursor = channels_col.find({
        "admin_id": ADMIN_ID
    })

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

    if count == 0:

        bot.send_message(
            ADMIN_ID,
            "No channels found. Click below to add one.",
            reply_markup=markup
        )

    else:

        bot.send_message(
            ADMIN_ID,
            "Your Managed Channels:",
            reply_markup=markup
        )


# ============================================================
# ADD CHANNEL
# ============================================================

@bot.message_handler(
    commands=["add"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def add_channel_start(message):

    msg = bot.send_message(
        ADMIN_ID,
        "Please ensure the bot is an Admin in your channel.\n\n"
        "Then FORWARD any message from that channel here."
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
            "❌ Error: Message was not forwarded.\n\nUse /add again."
        )


def finalize_channel(message, ch_id, ch_name):

    try:

        raw_plans = message.text.split(",")

        plans_dict = {}

        for p in raw_plans:

            t, pr = p.strip().split(":")

            plans_dict[t] = pr

        channels_col.update_one(
            {
                "channel_id": ch_id
            },
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

https://t.me/{bot_username}?start={ch_id}""",
            parse_mode="Markdown"
        )

    except Exception as e:

        print(e)

        bot.send_message(
            ADMIN_ID,
            """❌ Invalid format.

Use:

`1440:99,43200:199`""",
            parse_mode="Markdown"
        )


# ============================================================
# PAYMENT FLOW
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("select_")
)
def user_pays(call):

    _, ch_id, mins = call.data.split("_")

    ch_data = channels_col.find_one({
        "channel_id": int(ch_id)
    })

    price = float(ch_data["plans"][mins])

    USD_RATE = 100
    INR_RATE = 2

    usd_price = price / USD_RATE
    inr_price = price / INR_RATE

    plan_name = get_plan_name(int(mins))

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
            "✅ After payment, tap *I Have Paid*.\n"
            "📷 Then send your payment screenshot to the admin."
        ),
        reply_markup=markup,
        parse_mode="Markdown"
    )

    bot.send_message(
        call.message.chat.id,
        """📌 *Notice*

• Send the exact payment amount.
• Keep your payment screenshot.
• Tap ✅ *I Have Paid* after payment.
• Then send your screenshot to the admin.
• Verification usually takes a few minutes.

🙏 Thank you for your purchase!""",
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

    ch_data = channels_col.find_one({
        "channel_id": int(ch_id)
    })

    price = ch_data["plans"][mins]

    pending_payments[user_id] = {
        "channel_id": int(ch_id),
        "channel_name": ch_data["name"],
        "plan": mins,
        "price": price,
        "time": datetime.now()
    }

    bot.answer_callback_query(call.id)

    bot.send_message(
        user_id,
        """📷 *Upload Payment Screenshot*

Please send your payment screenshot as a *PHOTO*.

⚠️ Do NOT send:
• Screenshot as a file
• Video
• Text message

Once you upload the screenshot, it will automatically be forwarded to the admin.

⏳ Please upload it within 10 minutes.""",
        parse_mode="Markdown"
    )


# ============================================================
# PAYMENT WAITING
# ============================================================

@bot.message_handler(
    func=lambda m: m.from_user.id in pending_payments,
    content_types=["text"]
)
def waiting_for_screenshot(message):

    bot.reply_to(
        message,
        "📷 Please upload your payment screenshot as a PHOTO."
    )


@bot.message_handler(
    content_types=["document"]
)
def document_handler(message):

    if message.from_user.id not in pending_payments:
        return

    bot.reply_to(
        message,
        "❌ Please send the payment screenshot as a PHOTO, not as a document."
    )


@bot.message_handler(
    content_types=["photo"]
)
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
                callback_data=(
                    f"app_{user_id}_"
                    f"{payment['channel_id']}_"
                    f"{payment['plan']}"
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

        user_markup = InlineKeyboardMarkup()

        user_markup.add(
            InlineKeyboardButton(
                "📞 Contact Admin",
                url=f"https://t.me/{CONTACT_USERNAME}"
            )
        )

        bot.send_message(
            user_id,
            """✅ Screenshot Uploaded Successfully!

📷 Your payment screenshot has been forwarded to the admin.

⏳ Status: Waiting for admin verification.

🔔 Once approved, your invite link will be sent automatically.""",
            reply_markup=user_markup
        )

        del pending_payments[user_id]

    except Exception as e:

        print(f"PHOTO_HANDLER ERROR: {e}")


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

        expiry_ts = int(
            expiry_datetime.timestamp()
        )

        link = bot.create_chat_invite_link(
            ch_id,
            member_limit=1,
            expire_date=expiry_ts
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

        plan_name = get_plan_name(mins)

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

        bot.send_message(
            ADMIN_ID,
            f"❌ Error:\n{e}"
        )


# ============================================================
# PAYMENT REJECT
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data.startswith("rej_")
)
def reject_payment(call):

    user_id = int(
        call.data.split("_")[1]
    )

    bot.send_message(
        user_id,
        """❌ *Payment Rejected*

Your payment could not be verified.

Please check your payment and submit a new screenshot.

If you believe this is a mistake, contact the admin.""",
        parse_mode="Markdown"
    )

    bot.edit_message_text(
        "❌ Payment Rejected.",
        call.message.chat.id,
        call.message.message_id
    )


# ============================================================
# ============================================================
#             🏆 MEMBER COMPETITION SYSTEM
# ============================================================
# ============================================================


# ------------------------------------------------------------
# COMPETITION ADMIN PANEL
# ------------------------------------------------------------

@bot.message_handler(
    commands=["competition"],
    func=lambda m: m.from_user.id == ADMIN_ID
)
def competition_panel(message):

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID
    })

    markup = InlineKeyboardMarkup()

    markup.add(
        InlineKeyboardButton(
            "➕ Create / Configure",
            callback_data="comp_config"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🏆 Leaderboard",
            callback_data="comp_leaderboard"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "▶️ Start",
            callback_data="comp_start"
        ),
        InlineKeyboardButton(
            "⏹ Stop",
            callback_data="comp_stop"
        )
    )

    markup.add(
        InlineKeyboardButton(
            "🔄 Reset Scores",
            callback_data="comp_reset"
        )
    )

    if competition:

        status = (
            "🟢 ACTIVE"
            if competition.get("active")
            else "🔴 STOPPED"
        )

        group_name = competition.get(
            "group_name",
            "Not configured"
        )

        text = (
            "🏆 *Member Competition*\n\n"
            f"Status: {status}\n"
            f"👥 Group: {group_name}\n"
        )

        if competition.get("end_time"):

            remaining = (
                competition["end_time"]
                - datetime.now()
            )

            if remaining.total_seconds() > 0:

                text += (
                    f"⏳ Remaining: "
                    f"{str(remaining).split('.')[0]}\n"
                )

        rewards = competition.get(
            "rewards",
            {}
        )

        text += (
            "\n🎁 *Rewards*\n"
            f"🥇 1st: {rewards.get('1', 30)} Days\n"
            f"🥈 2nd: {rewards.get('2', 15)} Days\n"
            f"🥉 3rd: {rewards.get('3', 7)} Days\n"
            f"4️⃣ 4th: {rewards.get('4', 3)} Days\n"
            f"5️⃣ 5th: {rewards.get('5', 1)} Days"
        )

    else:

        text = (
            "🏆 *Member Competition*\n\n"
            "No competition configured yet."
        )

    bot.send_message(
        ADMIN_ID,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )


# ------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------

@bot.callback_query_handler(
    func=lambda call: call.data == "comp_config"
)
def competition_config(call):

    bot.answer_callback_query(call.id)

    msg = bot.send_message(
        ADMIN_ID,
        """⚙️ *Competition Setup*

First, FORWARD any message from the GROUP where the competition will run.

The bot must be an administrator in that group.""",
        parse_mode="Markdown"
    )

    bot.register_next_step_handler(
        msg,
        competition_get_group
    )


def competition_get_group(message):

    if not message.forward_from_chat:

        bot.send_message(
            ADMIN_ID,
            "❌ Please forward a message from the target group."
        )

        return

    chat = message.forward_from_chat

    if chat.type not in [
        "group",
        "supergroup"
    ]:

        bot.send_message(
            ADMIN_ID,
            "❌ That is not a group."
        )

        return

    group_id = chat.id
    group_name = chat.title

    msg = bot.send_message(
        ADMIN_ID,
        """⏱ Enter competition duration in DAYS.

Example:

7

This means the competition will run for 7 days."""
    )

    bot.register_next_step_handler(
        msg,
        competition_get_duration,
        group_id,
        group_name
    )


def competition_get_duration(
    message,
    group_id,
    group_name
):

    try:

        days = int(message.text)

        if days <= 0:
            raise ValueError

        msg = bot.send_message(
            ADMIN_ID,
            """🎁 Enter rewards for TOP 5.

Format:

30,15,7,3,1

Meaning:

🥇 1st = 30 Days
🥈 2nd = 15 Days
🥉 3rd = 7 Days
4️⃣ 4th = 3 Days
5️⃣ 5th = 1 Day"""
        )

        bot.register_next_step_handler(
            msg,
            competition_save_config,
            group_id,
            group_name,
            days
        )

    except:

        bot.send_message(
            ADMIN_ID,
            "❌ Invalid duration. Enter a number like 7."
        )


def competition_save_config(
    message,
    group_id,
    group_name,
    days
):

    try:

        rewards = [
            int(x.strip())
            for x in message.text.split(",")
        ]

        if len(rewards) != 5:
            raise ValueError

        competitions_col.update_one(
            {
                "admin_id": ADMIN_ID
            },
            {
                "$set": {
                    "admin_id": ADMIN_ID,
                    "group_id": group_id,
                    "group_name": group_name,
                    "duration_days": days,
                    "rewards": {
                        "1": rewards[0],
                        "2": rewards[1],
                        "3": rewards[2],
                        "4": rewards[3],
                        "5": rewards[4]
                    },
                    "active": False,
                    "end_time": None
                }
            },
            upsert=True
        )

        bot.send_message(
            ADMIN_ID,
            """✅ Competition Configured!

🏆 Group:
{}

⏱ Duration:
{} Days

🎁 Rewards:
🥇 {} Days
🥈 {} Days
🥉 {} Days
4️⃣ {} Days
5️⃣ {} Days

Use /competition to start it.""".format(
                group_name,
                days,
                rewards[0],
                rewards[1],
                rewards[2],
                rewards[3],
                rewards[4]
            )
        )

    except Exception:

        bot.send_message(
            ADMIN_ID,
            """❌ Invalid format.

Example:

30,15,7,3,1"""
        )


# ------------------------------------------------------------
# START COMPETITION
# ------------------------------------------------------------

@bot.callback_query_handler(
    func=lambda call: call.data == "comp_start"
)
def competition_start(call):

    bot.answer_callback_query(call.id)

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID
    })

    if not competition:

        bot.send_message(
            ADMIN_ID,
            "❌ Configure the competition first."
        )

        return

    end_time = (
        datetime.now()
        + timedelta(
            days=competition["duration_days"]
        )
    )

    competitions_col.update_one(
        {
            "admin_id": ADMIN_ID
        },
        {
            "$set": {
                "active": True,
                "start_time": datetime.now(),
                "end_time": end_time
            }
        }
    )

    # Clear previous scores
    competition_scores_col.delete_many({
        "group_id": competition["group_id"]
    })

    bot.send_message(
        ADMIN_ID,
        f"""🟢 *Competition Started!*

👥 Group:
{competition['group_name']}

⏱ Duration:
{competition['duration_days']} Days

🏆 Top 5 members will receive premium.

Good luck! 🔥""",
        parse_mode="Markdown"
    )


# ------------------------------------------------------------
# STOP COMPETITION
# ------------------------------------------------------------

@bot.callback_query_handler(
    func=lambda call: call.data == "comp_stop"
)
def competition_stop(call):

    bot.answer_callback_query(call.id)

    competitions_col.update_one(
        {
            "admin_id": ADMIN_ID
        },
        {
            "$set": {
                "active": False
            }
        }
    )

    bot.send_message(
        ADMIN_ID,
        "⏹ Competition stopped."
    )


# ------------------------------------------------------------
# RESET
# ------------------------------------------------------------

@bot.callback_query_handler(
    func=lambda call: call.data == "comp_reset"
)
def competition_reset(call):

    bot.answer_callback_query(call.id)

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID
    })

    if competition:

        competition_scores_col.delete_many({
            "group_id": competition["group_id"]
        })

    bot.send_message(
        ADMIN_ID,
        "🔄 Competition scores have been reset."
    )


# ============================================================
# MEMBER COUNTING
# ============================================================

@bot.message_handler(
    content_types=["new_chat_members"]
)
def new_members_handler(message):

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID,
        "active": True
    })

    if not competition:
        return

    if message.chat.id != competition["group_id"]:
        return

    # --------------------------------------------------------
    # Telegram service messages do not expose an adder in every
    # join scenario. We only credit when the sender is available.
    # --------------------------------------------------------

    adder = message.from_user

    if not adder:
        return

    # Do not count bot itself
    if adder.is_bot:
        return

    for new_user in message.new_chat_members:

        if new_user.is_bot:
            continue

        # Don't count self
        if new_user.id == adder.id:
            continue

        # Prevent same user being counted repeatedly
        already_added = competition_scores_col.find_one({
            "group_id": message.chat.id,
            "added_user_id": new_user.id
        })

        if already_added:
            continue

        competition_scores_col.update_one(
            {
                "group_id": message.chat.id,
                "user_id": adder.id
            },
            {
                "$inc": {
                    "count": 1
                },
                "$set": {
                    "username": adder.username,
                    "first_name": adder.first_name
                }
            },
            upsert=True
        )

        competition_scores_col.insert_one({
            "group_id": message.chat.id,
            "added_user_id": new_user.id,
            "adder_id": adder.id,
            "created_at": datetime.now()
        })


# ============================================================
# LEADERBOARD
# ============================================================

def get_leaderboard_text(group_id):

    scores = competition_scores_col.find(
        {
            "group_id": group_id,
            "user_id": {
                "$exists": True
            }
        }
    ).sort(
        "count",
        -1
    ).limit(5)

    lines = []

    medals = [
        "🥇",
        "🥈",
        "🥉",
        "4️⃣",
        "5️⃣"
    ]

    rank = 0

    for score in scores:

        rank += 1

        username = score.get(
            "username"
        )

        if username:

            name = f"@{username}"

        else:

            name = score.get(
                "first_name",
                str(score["user_id"])
            )

        lines.append(
            f"{medals[rank - 1]} "
            f"{name} — "
            f"**{score.get('count', 0)} members**"
        )

    if not lines:

        return "🏆 *Leaderboard*\n\nNo members counted yet."

    return (
        "🏆 *TOP MEMBER ADDERS*\n\n"
        + "\n".join(lines)
    )


@bot.message_handler(
    commands=["leaderboard"]
)
def leaderboard_command(message):

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID
    })

    if not competition:

        bot.reply_to(
            message,
            "❌ No competition is configured."
        )

        return

    if message.chat.id != competition["group_id"]:

        bot.reply_to(
            message,
            "❌ This command must be used in the competition group."
        )

        return

    bot.reply_to(
        message,
        get_leaderboard_text(
            competition["group_id"]
        ),
        parse_mode="Markdown"
    )


# ============================================================
# MY COUNT
# ============================================================

@bot.message_handler(
    commands=["mycount"]
)
def my_count(message):

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID,
        "active": True
    })

    if not competition:

        bot.reply_to(
            message,
            "❌ No active competition."
        )

        return

    if message.chat.id != competition["group_id"]:

        bot.reply_to(
            message,
            "❌ Use this command inside the competition group."
        )

        return

    score = competition_scores_col.find_one({
        "group_id": message.chat.id,
        "user_id": message.from_user.id
    })

    count = (
        score.get("count", 0)
        if score
        else 0
    )

    higher = competition_scores_col.count_documents({
        "group_id": message.chat.id,
        "user_id": {
            "$exists": True
        },
        "count": {
            "$gt": count
        }
    })

    rank = higher + 1

    bot.reply_to(
        message,
        f"""👤 *Your Competition Stats*

➕ Members Added: *{count}*
🏆 Current Rank: *#{rank}*""",
        parse_mode="Markdown"
    )


# ============================================================
# ADMIN LEADERBOARD
# ============================================================

@bot.callback_query_handler(
    func=lambda call: call.data == "comp_leaderboard"
)
def admin_leaderboard(call):

    bot.answer_callback_query(call.id)

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID
    })

    if not competition:

        bot.send_message(
            ADMIN_ID,
            "❌ No competition configured."
        )

        return

    bot.send_message(
        ADMIN_ID,
        get_leaderboard_text(
            competition["group_id"]
        ),
        parse_mode="Markdown"
    )


# ============================================================
# GIVE PREMIUM TO WINNERS
# ============================================================

def reward_competition_winners():

    competition = competitions_col.find_one({
        "admin_id": ADMIN_ID,
        "active": True
    })

    if not competition:
        return

    end_time = competition.get(
        "end_time"
    )

    if not end_time:
        return

    if datetime.now() < end_time:
        return

    group_id = competition["group_id"]

    rewards = competition.get(
        "rewards",
        {
            "1": 30,
            "2": 15,
            "3": 7,
            "4": 3,
            "5": 1
        }
    )

    winners = list(
        competition_scores_col.find({
            "group_id": group_id,
            "user_id": {
                "$exists": True
            }
        }).sort(
            "count",
            -1
        ).limit(5)
    )

    for index, winner in enumerate(winners):

        user_id = winner["user_id"]

        reward_days = int(
            rewards.get(
                str(index + 1),
                0
            )
        )

        if reward_days <= 0:
            continue

        try:

            # ------------------------------------------------
            # PREMIUM EXPIRY
            # ------------------------------------------------

            expiry = (
                datetime.now()
                + timedelta(
                    days=reward_days
                )
            )

            expiry_ts = int(
                expiry.timestamp()
            )

            # ------------------------------------------------
            # CREATE ONE-TIME PREMIUM LINK
            # ------------------------------------------------

            link = bot.create_chat_invite_link(
                group_id,
                member_limit=1,
                expire_date=expiry_ts
            )

            # ------------------------------------------------
            # SAVE INTO EXISTING USERS COLLECTION
            # ------------------------------------------------

            users_col.update_one(
                {
                    "user_id": user_id,
                    "channel_id": group_id
                },
                {
                    "$set": {
                        "expiry": expiry_ts
                    }
                },
                upsert=True
            )

            bot.send_message(
                user_id,
                f"""🎉 *CONGRATULATIONS!*

You finished *#{index + 1}* in the member competition!

👥 Members Added:
*{winner.get('count', 0)}*

🎁 Your Reward:
*{reward_days} Days Premium*

🔗 *Premium Join Link:*
{link.invite_link}

⚠️ This link can only be used once.

Enjoy your premium access! 🔥""",
                parse_mode="Markdown"
            )

        except Exception as e:

            print(
                f"WINNER ERROR {user_id}: {e}"
            )

    # --------------------------------------------------------
    # SAVE WINNERS
    # --------------------------------------------------------

    competitions_col.update_one(
        {
            "_id": competition["_id"]
        },
        {
            "$set": {
                "active": False,
                "finished": True,
                "finished_at": datetime.now(),
                "winners": [
                    {
                        "user_id": w["user_id"],
                        "count": w.get("count", 0)
                    }
                    for w in winners
                ]
            }
        }
    )

    try:

        bot.send_message(
            ADMIN_ID,
            "🏁 Competition finished!\n\n"
            "🎁 Premium rewards have been sent to the Top 5."
        )

    except:
        pass


# ============================================================
# CLEAR EXPIRED PAYMENT REQUESTS
# ============================================================

def clear_pending_payments():

    now = datetime.now()

    expired = []

    for user_id, data in list(
        pending_payments.items()
    ):

        if (
            now - data["time"]
        ).total_seconds() >= 600:

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

        pending_payments.pop(
            user_id,
            None
        )


# ============================================================
# AUTOMATIC KICK EXPIRED USERS
# ============================================================

def kick_expired_users():

    now = datetime.now().timestamp()

    expired_users = users_col.find({
        "expiry": {
            "$lte": now
        }
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

            users_col.delete_one({
                "_id": user["_id"]
            })

        except Exception as e:

            print(
                "EXPIRY ERROR:",
                e
            )


# ============================================================
# SCHEDULER
# ============================================================

if __name__ == "__main__":

    keep_alive()

    scheduler = BackgroundScheduler()

    # Existing systems
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

    # NEW competition system
    scheduler.add_job(
        reward_competition_winners,
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

        print(
            f"Polling error: {e}"
        )
