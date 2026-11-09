
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

INTERVAL = 2 * 60 * 60

DATA = Path("data")
QUEUE_FILE = DATA / "queue.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def load_queue():
    DATA.mkdir(exist_ok=True)
    if not QUEUE_FILE.exists():
        return []
    try:
        return json.loads(QUEUE_FILE.read_text())
    except Exception:
        return []

queue = load_queue()
lock = asyncio.Lock()


def save_queue():
    DATA.mkdir(exist_ok=True)
    temp = QUEUE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(queue, indent=2))
    temp.replace(QUEUE_FILE)


def owner(update):
    return (
        update.effective_user
        and update.effective_user.id == ADMIN_ID
        and update.effective_chat.type == "private"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    await update.message.reply_text(
        "🔥 TOSHIRO AUTO POST BOT ONLINE\n\n"
        "Send your new scripts or files here.\n"
        "Automatic posting every 2 hours."
    )


async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    doc = update.message.document

    async with lock:
        if any(x["unique_id"] == doc.file_unique_id for x in queue):
            await update.message.reply_text("File already saved!")
            return

        queue.append({
            "file_id": doc.file_id,
            "unique_id": doc.file_unique_id,
            "name": doc.file_name or "script",
            "caption": update.message.caption or "",
            "channel_done": False,
            "group_done": False
        })

        save_queue()

    await update.message.reply_text(
        f"✅ Saved: {doc.file_name or 'script'}\n"
        "Waiting for the next 2-hour posting cycle."
    )


async def deliver(context, item, destination, key):
    if item[key]:
        return True

    try:
        await context.bot.send_document(
            chat_id=destination,
            document=item["file_id"],
            caption=(item["caption"] or "TOSHIRO CPM")[:1024]
        )
        return True
    except Exception:
        logging.exception("Delivery failed: %s", item["name"])
        return False


async def auto_post(context: ContextTypes.DEFAULT_TYPE):
    async with lock:
        pending = [dict(x) for x in queue
                   if not x["channel_done"] or not x["group_done"]]

    for item in pending:
        channel_ok = await deliver(
            context, item, CHANNEL_ID, "channel_done"
        )
        group_ok = await deliver(
            context, item, GROUP_ID, "group_done"
        )

        async with lock:
            for saved in queue:
                if saved["unique_id"] == item["unique_id"]:
                    if channel_ok:
                        saved["channel_done"] = True
                    if group_ok:
                        saved["group_done"] = True
                    save_queue()
                    break

        await asyncio.sleep(1)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not owner(update):
        return

    async with lock:
        pending = sum(
            1 for x in queue
            if not x["channel_done"] or not x["group_done"]
        )

    await update.message.reply_text(
        f"🔥 TOSHIRO BOT ONLINE\n"
        f"Saved files: {len(queue)}\n"
        f"Pending files: {pending}\n"
        f"Interval: Every 2 hours"
    )


def main():
    if not all([BOT_TOKEN, ADMIN_ID, CHANNEL_ID, GROUP_ID]):
        raise RuntimeError("Missing environment variables!")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(
        MessageHandler(filters.Document.ALL, receive_file)
    )

    app.job_queue.run_repeating(
        auto_post,
        interval=INTERVAL,
        first=INTERVAL
    )

    app.run_polling()


if __name__ == "__main__":
    main()
