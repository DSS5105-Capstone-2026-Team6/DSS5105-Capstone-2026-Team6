"""
adapter — platform shells around DispatchDesk.

The core (desk/) never speaks to Telegram; this package does. session.py
holds the platform-independent part (per-chat session + confirmation
routing) with no third-party imports, so it is unit-testable; telegram_bot.py
is the thin python-telegram-bot wiring and holds zero business logic.
"""
