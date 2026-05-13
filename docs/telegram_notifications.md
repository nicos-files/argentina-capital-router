# Telegram Notifications

Optional Telegram notifications send a short, plain-text summary of the
daily capital plan to a chat of your choice. This is purely a notification
channel: it never places orders, never connects to a broker, and never
reads any of your private snapshots beyond the JSON artifacts that the
workflow already produces on disk.

**Manual review only. No live trading. No broker automation. No API keys
committed.**

## 1. Create a Telegram bot

1. Open Telegram and message `@BotFather`.
2. Send `/newbot` and follow the prompts to choose a name and username.
3. BotFather replies with a bot token of the form `123456:ABC...`. Treat
   this like a password.

## 2. Find your chat id

The simplest path:

1. Start a chat with your new bot and send it any message.
2. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser.
3. Look for the `"chat":{"id":...}` value in the response.

For group chats, add the bot to the group and read the same endpoint.

## 3. Provide credentials via environment variables

```bash
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="123456789"
```

These values are **never** read from any file in this repository.
`config/notifications/telegram.template.json` and
`config/notifications/telegram.example.json` describe only non-secret
settings (parse mode, max allocations, etc.); add a gitignored
`config/notifications/telegram.local.json` for any local overrides.

If you really need to override one of the values at the command line, pass
`--telegram-bot-token` / `--telegram-chat-id` to the relevant CLI. Tokens
passed via CLI may show up in your shell history; the environment-variable
path is preferred.

## 4. Dry-run a notification

Dry-run mode formats the message and prints the preview without making any
network call. It does not require a bot token or chat id.

```bash
python3 -m src.tools.notify_telegram \
  --plan snapshots/outputs/2026-05-12/capital_routing/daily_capital_plan.json \
  --dry-run
```

With an execution comparison:

```bash
python3 -m src.tools.notify_telegram \
  --plan snapshots/outputs/2026-05-12/capital_routing/daily_capital_plan.json \
  --execution-comparison snapshots/outputs/2026-05-12/manual_execution/manual_execution_comparison.json \
  --dry-run
```

Machine-readable output:

```bash
python3 -m src.tools.notify_telegram \
  --plan snapshots/outputs/2026-05-12/capital_routing/daily_capital_plan.json \
  --dry-run \
  --json
```

## 5. Real send

```bash
python3 -m src.tools.notify_telegram \
  --plan snapshots/outputs/2026-05-12/capital_routing/daily_capital_plan.json
```

Exit codes:

- `0` success (or dry-run preview generated)
- `1` send/validation failure (e.g. missing credentials, Telegram returned
  `ok=false`, network error)
- `2` CLI usage error

If Telegram rejects the message, the error text echoes Telegram's
`description` field with the bot token redacted. The token never appears
in raised exceptions, stdout, stderr, or any artifact on disk.

## 6. Integrate with the daily workflow

The orchestrator accepts the same flags so a single command can build the
plan and notify in one go.

Dry-run alongside the workflow (no credentials required):

```bash
python3 -m src.tools.run_manual_daily_workflow \
  --date 2026-05-12 \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --artifacts-dir snapshots/outputs/2026-05-12 \
  --telegram-dry-run
```

Real notification after the workflow:

```bash
python3 -m src.tools.run_manual_daily_workflow \
  --date 2026-05-12 \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --executions snapshots/manual_execution/2026-05-12.json \
  --usdars-rate 1200 \
  --artifacts-dir snapshots/outputs/2026-05-12 \
  --notify-telegram
```

If both `--telegram-dry-run` and `--notify-telegram` are passed, dry-run
wins and no message is sent.

When Telegram is enabled, the workflow's JSON summary (`--json`) gains a
`telegram` block:

```json
{
  "telegram": {
    "ok": true,
    "dry_run": false,
    "sent": true,
    "message_length": 312
  }
}
```

A Telegram send failure returns exit code 1, but the daily plan, report,
and any comparison artifacts have already been written and are kept.

## Security reminders

- **Never commit tokens.** `.env`, `.env.*`, `.local/`, and
  `config/notifications/telegram.local.json` are gitignored on purpose.
- **Manual review only.** Telegram is a one-way notification channel. The
  bot does not accept commands and never places trades.
- **No broker automation.** The notifier never reads broker APIs.
- **Token is never logged.** The notifier redacts the bot token from
  errors before raising them.

## Sample message

```
Argentina Capital Router - 2026-05-12

Decision: INVEST_DIRECT_LONG_TERM
Manual review only. No live trading.

Monthly contribution: USD 200.00
Portfolio value: USD 170.83

Recommended manual review allocation:
1. SPY - USD 133.60
2. AAPL - USD 22.13
3. KO - USD 22.13
4. MELI - USD 22.13

Skipped: 6 below min trade
Warnings: 2

Execution comparison:
Follow rate: 50.0%
Matched: 0 | Partial: 1 | Missed: 1 | Extra: 0
```
