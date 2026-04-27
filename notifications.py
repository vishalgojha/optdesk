#!/usr/bin/env python3
"""
Notifications Module
Supports: WhatsApp (Twilio), Telegram, Email
"""

import os
import sqlite3
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from datetime import datetime
from typing import Optional

DB = Path(__file__).parent / "notifications.db"


def init_notifications_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            channel TEXT NOT NULL,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT DEFAULT 'sent',
            error TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS configs (
            channel TEXT PRIMARY KEY,
            config TEXT NOT NULL,
            enabled INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()


def save_config(channel: str, config: dict, enabled: bool = True):
    conn = sqlite3.connect(DB)
    conn.execute("""
        INSERT OR REPLACE INTO configs (channel, config, enabled)
        VALUES (?, ?, ?)
    """, (channel, json.dumps(config), 1 if enabled else 0))
    conn.commit()
    conn.close()


def get_config(channel: str) -> Optional[dict]:
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT config, enabled FROM configs WHERE channel = ?", (channel,)
    ).fetchone()
    conn.close()
    if row and row[1]:
        return json.loads(row[0])
    return None


def log_notification(channel: str, recipient: str, message: str, status: str, error: str = None):
    conn = sqlite3.connect(DB)
    conn.execute("""
        INSERT INTO notifications (timestamp, channel, recipient, message, status, error)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (datetime.now().isoformat(), channel, recipient, message, status, error))
    conn.commit()
    conn.close()


# ── WhatsApp (Twilio) ─────────────────────────────────────────────────────

def send_whatsapp(to: str, message: str) -> bool:
    config = get_config("whatsapp")
    if not config:
        print("⚠️  WhatsApp not configured")
        return False

    try:
        from twilio.rest import Client
        client = Client(config.get("account_sid"), config.get("auth_token"))
        client.messages.create(
            from_=config.get("from"),
            body=message,
            to=to
        )
        log_notification("whatsapp", to, message, "sent")
        print(f"✅ WhatsApp sent to {to}")
        return True
    except Exception as e:
        log_notification("whatsapp", to, message, "failed", str(e))
        print(f"❌ WhatsApp failed: {e}")
        return False


def setup_whatsapp(account_sid: str, auth_token: str, from_number: str):
    save_config("whatsapp", {
        "account_sid": account_sid,
        "auth_token": auth_token,
        "from": from_number
    })


# ── Telegram ────────────────────────────────────────────────────────────

def send_telegram(chat_id: str, message: str) -> bool:
    config = get_config("telegram")
    if not config:
        print("⚠️  Telegram not configured")
        return False

    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{config.get('bot_token')}/sendMessage"
        data = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        log_notification("telegram", chat_id, message, "sent")
        print(f"✅ Telegram sent to {chat_id}")
        return True
    except Exception as e:
        log_notification("telegram", chat_id, message, "failed", str(e))
        print(f"❌ Telegram failed: {e}")
        return False


def setup_telegram(bot_token: str):
    save_config("telegram", {"bot_token": bot_token})


# ── Email ────────────────────────────────────────────────────────────────

def send_email(to: str, subject: str, body: str) -> bool:
    config = get_config("email")
    if not config:
        print("⚠️  Email not configured")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = config.get("from")
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(config.get("smtp_host"), config.get("smtp_port", 587)) as server:
            server.starttls()
            server.login(config.get("username"), config.get("password"))
            server.sendmail(config.get("from"), to, msg.as_string())

        log_notification("email", to, f"{subject}: {body[:50]}", "sent")
        print(f"✅ Email sent to {to}")
        return True
    except Exception as e:
        log_notification("email", to, f"{subject}: {body[:50]}", "failed", str(e))
        print(f"❌ Email failed: {e}")
        return False


def setup_email(smtp_host: str, smtp_port: int, username: str, password: str, from_addr: str):
    save_config("email", {
        "smtp_host": smtp_host,
        "smtp_port": smtp_port,
        "username": username,
        "password": password,
        "from": from_addr
    })


# ── Signal Notifications ─────────────────────────────────────────────────

def notify_signal(signal_data: dict, channels: list = None):
    """Send signal notification to configured channels"""
    message = format_signal_message(signal_data)

    if not channels:
        channels = []
        if get_config("whatsapp"): channels.append("whatsapp")
        if get_config("telegram"): channels.append("telegram")
        if get_config("email"): channels.append("email")

    for ch in channels:
        if ch == "whatsapp":
            send_whatsapp(get_config("whatsapp").get("to", ""), message)
        elif ch == "telegram":
            send_telegram(get_config("telegram").get("chat_id", ""), message)
        elif ch == "email":
            send_email(
                get_config("email").get("to", ""),
                f"NSE Signal: {signal_data.get('signal', 'NEUTRAL')}",
                message
            )


def format_signal_message(sig: dict) -> str:
    emoji = {"BULLISH": "🟢", "BEARISH": "🔴", "NEUTRAL": "🟡", "SIDEWAYS": "🟠"}.get(sig.get("signal", ""), "⚪")
    return f"""
📊 NSE Option Chain Signal

{emoji} {sig.get('signal', 'NIFTY')} | {sig.get('confidence', 'MEDIUM')} Confidence

📍 ATM: {sig.get('atm', '-')}
📊 PCR: {sig.get('pcr_total', '-')}
📈 Range: {sig.get('spot_range_today', {}).get('low', '-')} - {sig.get('spot_range_today', {}).get('high', '-')}

🛡️ Support: {', '.join(map(str, sig.get('key_support', [])))}
🚧 Resistance: {', '.join(map(str, sig.get('key_resistance', [])))}

📌 {sig.get('suggested_strategy', 'N/A')}
📝 {sig.get('summary', '')}

❌ Invalidation: {sig.get('invalidation', '-')}
"""


if __name__ == "__main__":
    init_notifications_db()
    print("Notifications DB initialized")

    # Example setup
    # setup_telegram("BOT_TOKEN")
    # setup_whatsapp("SID", "TOKEN", "whatsapp:+1234567890")
    # setup_email("smtp.gmail.com", 587, "user", "pass", "alerts@example.com")
