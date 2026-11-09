
import os
import json
import logging
import asyncio
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID")
GROUP_ID = os.getenv("GROUP_ID")

INTERVAL = 7200
POST_TEXT = os.getenv(
    "POST_TEXT",
    "🔥 TOSHIRO CPM\n\nNew script available!\nDownload the file below."
)

DATA = Path("data")
QUEUE_FILE = DATA / "queue.json"
SETTINGS_FILE = DATA / "settings.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def read_json(path, default):
    DATA.mkdir(exist_ok=True)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        logging.exception("JSON read failed: %s", path)
        return default


queue = read_json(QUEUE_FILE, [])
settings = read_json(SETTINGS_FILE, {})
lock = asyncio.Lock()


def save_queue():
    DATA.mkdir(exist_ok=True)
    temp = QUEUE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(queue, indent=2))
    temp.replace(QUEUE_FILE)


def save_settings():
    DATA.mkdir(exist_ok=True)
    temp = SETTINGS_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2))
    temp.replace(SETTINGS_FILE)


def owner(update):
    return bool(
        update.effective_user
        and update.effective_user.id == ADMIN_ID
        and update.effective_chat
        and update.effective_chat.type == "private"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    await update.effective_message.reply_text(
        "🔥 TOSHIRO AUTO POST BOT ONLINE\n\n"
        "1. Send your banner photo first.\n"
        "2. Send your new scripts or files.\n"
        "3. Every 2 hours, new files will be posted "
        "to your channel and group.\n\n"
        "/status - Bot status\n"
        "/queue - Pending files"
    )


async def receive_banner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    photo = update.effective_message.photo[-1]

    async with lock:
        settings["banner_file_id"] = photo.file_id
        save_settings()

    await update.effective_message.reply_text(
        "✅ Banner saved!\n"
        "This banner will appear above the announcement text "
        "in future posts."
    )


async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    doc = update.effective_message.document

    async with lock:
        if any(x["unique_id"] == doc.file_unique_id for x in queue):
            await update.effective_message.reply_text(
                "This file is already in the queue."
            )
            return

        queue.append({
            "file_id": doc.file_id,
            "unique_id": doc.file_unique_id,
            "name": doc.file_name or "script",
            "channel_done": False,
            "group_done": False
        })

        save_queue()

    await update.effective_message.reply_text(
        f"✅ New file saved: {doc.file_name or 'script'}\n"
        "Waiting for the next 2-hour posting cycle."
    )


async def deliver(context, item, destination, prefix):
    banner_key = prefix + "_banner_done"
    file_key = prefix + "_file_done"

    try:
        if not item.get(banner_key):
            banner_id = settings.get("banner_file_id")

            if banner_id:
                await context.bot.send_photo(
                    chat_id=destination,
                    photo=banner_id,
                    caption=POST_TEXT[:1024]
                )
            else:
                await context.bot.send_message(
                    chat_id=destination,
                    text=POST_TEXT
                )

            async with lock:
                for saved in queue:
                    if saved["unique_id"] == item["unique_id"]:
                        saved[banner_key] = True
                        save_queue()
                        break

        if not item.get(file_key):
            await context.bot.send_document(
                chat_id=destination,
                document=item["file_id"],
                caption=f"📁 {item['name']}"
            )

            async with lock:
                for saved in queue:
                    if saved["unique_id"] == item["unique_id"]:
                        saved[file_key] = True
                        save_queue()
                        break

        return True

    except Exception:
        logging.exception(
            "Post failed for %s to %s",
            item["name"],
            destination
        )
        return False


async def auto_post(context: ContextTypes.DEFAULT_TYPE):
    async with lock:
        pending = [
            dict(item) for item in queue
            if not item.get("channel_file_done")
            or not item.get("group_file_done")
        ]

    for item in pending:
        await deliver(
            context, item, CHANNEL_ID, "channel"
        )

        await deliver(
            context, item, GROUP_ID, "group"
        )

        await asyncio.sleep(1)

    logging.info("Posting cycle completed.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    async with lock:
        pending = sum(
            1 for x in queue
            if not x.get("channel_file_done")
            or not x.get("group_file_done")
        )

    banner = "SET" if settings.get("banner_file_id") else "NOT SET"

    await update.effective_message.reply_text(
        "🔥 TOSHIRO AUTO POST BOT\n\n"
        "Status: ONLINE\n"
        f"Saved files: {len(queue)}\n"
        f"Pending files: {pending}\n"
        f"Banner: {banner}\n"
        "Interval: Every 2 hours"
    )


async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    async with lock:
        names = [
            x["name"] for x in queue
            if not x.get("channel_file_done")
            or not x.get("group_file_done")
        ]

    if not names:
        await update.effective_message.reply_text("No pending files.")
        return

    await update.effective_message.reply_text(
        "📂 Pending files:\n\n" + "\n".join(names[:30])
    )


def main():
    if not all([BOT_TOKEN, ADMIN_ID, CHANNEL_ID, GROUP_ID]):
        raise RuntimeError("Missing environment variables!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("queue", show_queue))

    app.add_handler(
        MessageHandler(filters.PHOTO, receive_banner)
    )

    app.add_handler(
        MessageHandler(filters.Document.ALL, receive_file)
    )

    app.job_queue.run_repeating(
        auto_post,
        interval=INTERVAL,
        first=INTERVAL
    )

    logging.info("TOSHIRO AUTO POST BOT started.")

    app.run_polling()


if __name__ == "__main__":
    main()
