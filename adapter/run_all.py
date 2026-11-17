"""adapter/run_all.py — one free Render service, two duties.

The Telegram bot (long polling) runs in a background thread; the FastAPI
web frontend (uvicorn) runs in the foreground on $PORT and answers
Render's health checks. The bot's own mini health server stays off —
uvicorn owns $PORT. One instance, one Supabase ledger, one secret set,
and the existing UptimeRobot monitor keeps both halves awake.

Run:  python -m adapter.run_all
"""

import os
import threading


def main():
    port = int(os.environ.get("PORT", "8000") or 8000)
    # telegram_bot.main() would bind $PORT for its health stub; keep it off
    os.environ.pop("PORT", None)

    from adapter import telegram_bot
    threading.Thread(target=telegram_bot.main, daemon=True,
                     name="telegram-bot").start()

    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
