# skill:delux-gateway
## Summary
Delux Gateway — bidirectional Telegram bridge. Runs Delux as a Telegram bot for remote infrastructure management.

## When To Use
- Running the agent remotely from your phone
- Receiving async notifications with results
- Managing infrastructure from anywhere
- Interactive sessions via Telegram DM

## Setup
1. Create a bot via @BotFather on Telegram
2. Configure `~/.delux/telegram.json`:
   ```json
   {"token": "YOUR_BOT_TOKEN", "chat_id": "YOUR_CHAT_ID"}
   ```
3. Start the gateway:
   ```
   delux-gateway
   ```

## Commands (via Telegram)
- `/start` — Welcome message
- `/status` — Agent status and uptime
- `/cancel` — Cancel running task
- `/stats` — Session statistics
- Any other text — Run as a Delux prompt

## Steps
1. Start long-polling the Telegram API
2. On each message, run it through the Delux agent
3. Send step-by-step results back to Telegram
4. Send the final answer when complete

## Response Examples

### Agent starts gateway
```json
{"action":"run_skill","skill":"delux-gateway","args":"start","timeout":10}
```

### Gateway status
```json
{
  "status": "running",
  "chat_id": "123456789",
  "mode": "long-polling",
  "poll_interval": "1s",
  "sessions": 5
}
```

### Prompt injection example
```
--- delux-gateway example ---
USER: "start the telegram gateway"
AGENT: {"action":"run_skill","skill":"delux-gateway","args":"start","timeout":10}
RESULT: {"status":"running","chat_id":"123456789","mode":"long-polling"}
NEXT ACTION: {"action":"final","message":"Gateway started. Send /start from Telegram to begin."}
```

## Caveats
- Requires the agent to be installed and configured
- Long-running tasks may timeout (default 5 min)
- One conversation at a time per chat_id
- Bot token must have write access to the chat
