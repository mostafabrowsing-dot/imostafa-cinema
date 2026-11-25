# iMostafa Cinema

Telegram notifications for newly bookable movies and newly added booking dates at VOX City Centre Almaza, across all auditorium types.

## Setup

1. Add a repository Actions secret named `TELEGRAM_BOT_TOKEN` with your BotFather token.
2. Open Actions → iMostafa Cinema → Run workflow.
3. Send `/start` to your Telegram bot. Friends can do the same. `/stop` unsubscribes.

The first successful scan establishes a baseline and sends no historic notifications. Newly added dates are grouped per movie. Advance bookings are detected through actual bookable sessions, not inferred from a coming-soon listing. If VOX lists no sessions, the previous state is retained. A full scan visits today and all future booking dates linked by VOX.

GitHub Actions checks on a five-minute schedule, but runs can be delayed or dropped. Start/stop commands are processed on the next run, not instantly. Public repository schedules can be disabled after 60 days without activity. Review Actions failures periodically.

Subscriber IDs, pending messages, update offsets and previously seen dates are encrypted in `state.enc`, using a key derived from the bot token. Never commit the token. Token rotation requires deliberate state migration or deletion of `state.enc` and resubscription. Losing state resets the baseline. Owners with access to the token can decrypt state.

Delivery retries are retained per subscriber. A crash after Telegram accepts a message but before state is committed can cause duplicate delivery; exactly-once delivery is not guaranteed. New showtimes within an already known date do not trigger alerts.

Run tests with `python -m unittest -v`; test website access with `python bot.py --check`. Live Telegram delivery remains unverified until the secret is configured.
