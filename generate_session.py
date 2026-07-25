"""
Run this ONCE, locally in Termux, to log in and generate a session
string. It'll ask for your phone number and the login code Telegram
sends you. Copy the printed string into Render's SESSION_STRING
environment variable — never commit it to GitHub, it's effectively
your account password.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API ID: "))
api_hash = input("API Hash: ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nLogged in. Your session string (keep this secret):\n")
    print(client.session.save())
