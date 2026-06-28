import sys
import json
import os
import urllib.request
import urllib.parse

def send_telegram(message):
    config_path = os.path.expanduser("~/.delux/telegram.json")
    
    if not os.path.exists(config_path):
        return ("ERROR: Telegram not configured. Please create ~/.delux/telegram.json with: "
                '{"token": "YOUR_BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"}')

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        token = config.get("token")
        chat_id = config.get("chat_id")
        
        if not token or not chat_id:
            return "ERROR: Missing token or chat_id in telegram.json"

        # Formatear el mensaje para Telegram
        text = f"🤖 *Delux Agent Update:*\n\n{message}"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as response:
            res = json.loads(response.read().decode())
            if res.get("ok"):
                return "SUCCESS: Notification sent to Telegram."
            else:
                return f"ERROR: Telegram API returned: {res.get('description')}"

    except Exception as e:
        return f"ERROR: Failed to send telegram message: {str(e)}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: delux-telegram-notify <message>")
        sys.exit(1)
    
    msg = " ".join(sys.argv[1:])
    print(send_telegram(msg))
