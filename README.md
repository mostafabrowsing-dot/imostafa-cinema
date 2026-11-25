# VOX Cinemas Alerts

Independent Telegram booking alerts for **@VoxCinemasAlertsBot** and all cinemas discovered from VOX Egypt's live cinema filters.

## Behavior
- Each cinema has independent movie/date history and health.
- First successful scan of each cinema silently establishes a baseline.
- Alerts cover newly bookable movies and previously unknown booking dates. Same-day session/format changes and reopening known days are silent.
- Actual dates are read from the page, including distant pre-booking dates; mismatched responses fail safely.
- Failed branches retain their history while the others update. Warning after three consecutive failures; recovery notice on success.
- English private-chat commands: `/start`, `/status`, `/test`, `/stop`. Every subscriber receives all cinemas. TEST goes only to its requesting chat.
- Posters fall back to text. Booking links are filtered by cinema and movie. Seat availability is not verified.

## Activate Telegram
1. Repository Settings → Secrets and variables → Actions → New repository secret.
2. Name: `TELEGRAM_BOT_TOKEN`. Paste the BotFather token directly there; never in a file or chat.
3. Actions → Cinema automatic checks → Run workflow → main.
4. Open https://t.me/VoxCinemasAlertsBot and send `/start`; run again to process the command, then test `/status` and `/test`.
5. Check the per-cinema status, not only the green workflow result. The workflow may successfully persist state after a source failure.

BotFather `/setcommands`:
```
start - Enable VOX Egypt booking alerts
status - View monitoring status and last check
test - Preview a movie notification
stop - Disable notifications
```

## Scheduler (Cloudflare)
Deploy `cloudflare-worker.js`. Add secret `GITHUB_TOKEN` containing a fine-grained GitHub PAT restricted to this repository with Actions read/write and Metadata read. Set text variables:
- `GITHUB_OWNER=mostafabrowsing-dot`
- `GITHUB_REPO=vox-cinemas-alerts`

Add exactly one Cron trigger: `* * * * *`. GET on the Worker only checks workflow access; verify scheduled logs show dispatch HTTP 204 and GitHub actually executes. No GitHub schedule is configured, so the Worker is required for recurring runs. Cron propagation can take time.

Requests every minute are not a guarantee of delivery within 60 seconds. Actions queues, network requests, polling and delivery can add delay. Runs share a single concurrency group. Long scans may coalesce queued runs. Watch run duration; do not add overlapping consumers of the same token.

## Development
Python 3.12:
```
pip install -r requirements.txt
python -m unittest -v
python bot.py --check
```
`--check` needs no token, sends nothing and fails if any discovered branch cannot be verified. Requests are limited to three globally; cinemas scan sequentially. Cinema names/filter values are discovered from live HTML, not guessed.

## State and limitations
`state.enc` is Fernet encrypted using SHA256 of the bot token. Do not change the token without planning migration/reset of subscribers and baselines. No original project state or credentials are used.

State is atomically written locally and committed with five retries of the same commit. No force pushes. Telegram delivery and git persistence cannot be atomic: a permanent save failure after delivery can cause duplicates. Exactly-once delivery is not guaranteed. Telegram replies/deliveries retry when pending; blocked chats can retain pending queues. The bot is public to anyone with its link.

Missing cinema filters retain known branches and mark discovery delayed. A completely stopped scheduler cannot notify users about its own outage. One deployment only; active webhooks are rejected. Confirm public standard-runner availability and account limits before use.

## Validation at implementation
11 fixture tests cover filter discovery, mixed-page cinema isolation, sold-out history, silent per-cinema baseline, new day and deduplication, failure isolation and recovery, page date rollover, far future days, date mismatch, stale pages, and TEST privacy.

Telegram identity, real command delivery, encrypted production state, and Cloudflare scheduled dispatch require your private secrets and activation; these are not claimed as verified before setup.

Sources: https://egy.voxcinemas.com/showtimes · https://core.telegram.org/bots/api · https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event · https://developers.cloudflare.com/workers/configuration/cron-triggers/
