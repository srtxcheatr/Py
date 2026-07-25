"""
Bypass Relay — Backend
=======================
A small web server that sits between your website and your userbot.
The website POSTs a link here, this sends it to the other bot as your
real account, waits for the reply, and sends the result back as JSON.

REQUIREMENTS (put these in requirements.txt too):
    flask
    flask-cors
    telethon

ENVIRONMENT VARIABLES (set these on Render, don't hardcode them):
    API_ID          - numeric, from my.telegram.org
    API_HASH        - string, from my.telegram.org
    SESSION_STRING  - generated once by running generate_session.py locally
    TARGET_BOT      - @username of the other bot, e.g. @the_other_bot

Why a session STRING instead of a session FILE: Render's disk resets
on every deploy, so a saved .session file would vanish and you'd have
to log in again each time. A string session lives entirely in an
environment variable, so it survives redeploys.
"""

import os
import time
from datetime import datetime, timezone
from threading import Lock

from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
TARGET_BOT = os.environ.get("TARGET_BOT", "@the_other_bot")

POLL_TIMEOUT = 20   # seconds to wait for the other bot's reply
POLL_INTERVAL = 1   # seconds between checks

app = Flask(__name__)
CORS(app)  # allows your website (a different domain) to call this API

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
client.connect()

# Only one request talks to Telegram at a time — keeps replies from
# getting mixed up between two people using the site at once. It means
# requests queue rather than run in parallel, which is fine at small
# scale; revisit if you ever need real concurrency.
request_lock = Lock()


def wait_for_reply(after: datetime):
    """Polls the chat with the target bot until a message newer than
    `after` shows up, or gives up after POLL_TIMEOUT seconds."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        messages = client.get_messages(TARGET_BOT, limit=1)
        if messages and messages[0].date > after:
            return messages[0].raw_text
        time.sleep(POLL_INTERVAL)
    return None


@app.route("/api/bypass", methods=["POST"])
def bypass():
    data = request.get_json(silent=True) or {}
    link = (data.get("link") or "").strip()
    if not link:
        return jsonify({"error": "No link provided."}), 400

    with request_lock:
        sent_at = datetime.now(timezone.utc)
        client.send_message(TARGET_BOT, link)
        result = wait_for_reply(sent_at)

    if result is None:
        return jsonify({"error": "The relay bot didn't reply in time."}), 504
    return jsonify({"result": result})


@app.route("/", methods=["GET"])
def health():
    # Render pings this to check the service is alive
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # Render sets PORT for you
    app.run(host="0.0.0.0", port=port, threaded=False)
