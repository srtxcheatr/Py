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

POLL_TIMEOUT = 20   # overall seconds to wait before giving up
POLL_INTERVAL = 1   # seconds between checks
QUIET_PERIOD = 3    # seconds of silence that means the bot is done sending

app = Flask(__name__)
CORS(app)  # allows your website (a different domain) to call this API

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
client.connect()

# Only one request talks to Telegram at a time — keeps replies from
# getting mixed up between two people using the site at once. It means
# requests queue rather than run in parallel, which is fine at small
# scale; revisit if you ever need real concurrency.
request_lock = Lock()


def collect_replies(after: datetime):
    """Some bots send more than one message per request (a 'processing...'
    line, then the real result, sometimes a footer after that). Instead of
    grabbing the first new message, this collects every new message and
    stops once the bot has gone quiet for QUIET_PERIOD seconds — meaning
    it's likely done sending — or POLL_TIMEOUT is reached overall."""
    seen = {}
    last_new_at = time.time()
    deadline = time.time() + POLL_TIMEOUT

    while time.time() < deadline:
        for m in client.get_messages(TARGET_BOT, limit=10):
            if m.date > after and m.id not in seen:
                seen[m.id] = (m.date, m.raw_text)
                last_new_at = time.time()

        if seen and (time.time() - last_new_at) >= QUIET_PERIOD:
            break
        time.sleep(POLL_INTERVAL)

    # oldest first, matching the order the bot actually sent them
    ordered = [text for _, text in sorted(seen.values(), key=lambda x: x[0])]
    return ordered


def pick_result(replies):
    """Out of everything the bot sent, prefer whichever message actually
    looks like a link — that's almost always the real result, not a
    'processing' or 'thanks for using this bot' message. Adjust this if
    your target bot's real answer doesn't contain a URL."""
    if not replies:
        return None
    for text in replies:
        if "http://" in text or "https://" in text:
            return text
    return replies[-1]  # fallback: nothing looked like a link, use the last message


@app.route("/api/bypass", methods=["POST"])
def bypass():
    data = request.get_json(silent=True) or {}
    link = (data.get("link") or "").strip()
    if not link:
        return jsonify({"error": "No link provided."}), 400

    with request_lock:
        sent_at = datetime.now(timezone.utc)
        client.send_message(TARGET_BOT, link)
        replies = collect_replies(sent_at)
        result = pick_result(replies)

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
