"""
adapter/telegram_bot.py — the python-telegram-bot wiring around ChatSession.

This file holds ZERO business logic: it filters triggers, strips the
@mention, renders options as inline keyboard buttons, splits over-long
replies, and sends text back. Everything the desk decides happens in desk/.

Setup:
    1. BotFather -> /newbot -> copy the token into .env as
       TELEGRAM_BOT_TOKEN = "123456:ABC..."
    2. Add the bot to the group. Telegram bots see all group messages only
       when the group privacy mode is OFF (BotFather -> /setprivacy ->
       Disable) — otherwise they only see @mentions and replies, which is
       also fine: this adapter only acts on @mentions in groups anyway.
    3. Run:  uv run python -m adapter.telegram_bot

One DispatchDesk per chat, so two groups never share queues (adapter/session.py).
Behind a local proxy set HTTPS_PROXY — httpx picks it up like the LLM calls.
"""

import os
import sys
import traceback
from pathlib import Path

try:
    from desk.config import PROJECT_ROOT
    from adapter.session import (ChatSession, split_reply, strip_mention,
                                 wants_bot)
except ImportError:  # run directly as a script
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from desk.config import PROJECT_ROOT
    from adapter.session import (ChatSession, split_reply, strip_mention,
                                 wants_bot)

ENV_PATH = PROJECT_ROOT / ".env"
TOKEN_VAR = "TELEGRAM_BOT_TOKEN"


def _session_factory():
    from desk.desk import DispatchDesk
    return DispatchDesk(persona="group")


def build_application(token, make_session=None):
    """Wire handlers. make_session is injectable for tests; production builds
    a ChatSession wrapping a group-persona DispatchDesk."""
    from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                              CommandHandler, MessageHandler, filters)

    sessions = {}   # chat_id -> ChatSession
    make_session = make_session or (lambda: ChatSession(_session_factory))

    def session_for(chat_id):
        if chat_id not in sessions:
            sessions[chat_id] = make_session()
        return sessions[chat_id]

    async def send_reply(message, reply, options):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        markup = None
        if options:
            rows = [[InlineKeyboardButton(o, callback_data=f"opt:{o}")]
                    for o in options]
            markup = InlineKeyboardMarkup(rows)
        chunks = split_reply(reply)
        for i, chunk in enumerate(chunks):
            await message.reply_text(
                chunk, reply_markup=markup if i == len(chunks) - 1 else None)

    async def on_start(update, context):
        await update.effective_message.reply_text(
            "Dispatch desk is live. Send an order line, or @mention me in a "
            "group. I never commit an allocation until someone says yes.")

    async def on_message(update, context):
        msg, chat = update.effective_message, update.effective_chat
        if msg is None or not msg.text:
            return
        username = context.bot.username or ""
        private = chat.type == "private"
        if not wants_bot(msg.text, private=private, bot_username=username):
            return   # group chatter without an @mention: not ours
        text = msg.text if private else strip_mention(msg.text, username)
        who = (update.effective_user.full_name
               or update.effective_user.username or "member")
        try:
            reply, options = session_for(chat.id).handle(text, requester=who)
        except Exception:
            traceback.print_exc()
            reply, options = "Something went wrong on my side — try again.", []
        await send_reply(msg, reply, options)

    async def on_option(update, context):
        """A tapped OPTIONS button re-enters the session as if the member had
        typed that choice, so clarification loops work over buttons too."""
        query = update.callback_query
        await query.answer()
        if not (query.data or "").startswith("opt:"):
            return
        chat_id = query.message.chat_id
        session = sessions.get(chat_id)
        if session is None:
            return
        who = (query.from_user.full_name
               or query.from_user.username or "member")
        try:
            reply, options = session.handle(query.data[4:], requester=who)
        except Exception:
            traceback.print_exc()
            reply, options = "Something went wrong on my side — try again.", []
        await send_reply(query.message, reply, options)

    app = (ApplicationBuilder().token(token).build())
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CallbackQueryHandler(on_option))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   on_message))
    return app


def main():
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
    token = os.environ.get(TOKEN_VAR, "").strip()
    if not token:
        raise SystemExit(f"{TOKEN_VAR} not found in {ENV_PATH} — create it "
                         "via BotFather (/newbot), then rerun.")
    print("Dispatch bot polling…  (Ctrl+C to stop)")
    build_application(token).run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
