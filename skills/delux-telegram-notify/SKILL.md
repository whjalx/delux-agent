# skill:delux-telegram-notify
## Summary
Sends a status update or notification to the user's Telegram. Use to inform about background progress, completed tasks, or important alerts.

## When To Use
- Sending notifications for long-running tasks that complete
- Alerting the user about errors or critical situations
- Providing progress updates during multi-step operations
- Communicating with the user asynchronously

## Usage
delux-telegram-notify "<message>"

## Steps
1. Read Telegram bot token and chat ID from ~/.delux/telegram.json
2. Format message with Markdown for Telegram
3. Send via Telegram Bot API (api.telegram.org)
4. Return success or error based on API response

## Response Examples

### Agent invoca la skill
```json
{"action":"run_skill","skill":"delux-telegram-notify","args":"Backup completed successfully. 2.3GB processed.","timeout":15}
```

### Skill devuelve resultado
```
SUCCESS: Notification sent to Telegram.
```

### Prompt injection example (para few-shot learning)
```
--- delux-telegram-notify example ---
USER: "let me know when the deployment finishes"
AGENT: {"action":"run_skill","skill":"delux-telegram-notify","args":"Deployment finished: all services running.","timeout":15}
RESULT: SUCCESS: Notification sent to Telegram.
NEXT ACTION: {"action":"final","message":"Notified user via Telegram"}
```

## Caveats
- Requires `~/.delux/telegram.json` with `{"token": "...", "chat_id": "..."}`
- Requires internet connectivity to reach Telegram API
- Message must be a single string; use \n for line breaks
- Telegram has a 4096 character limit per message
