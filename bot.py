import base64
import hashlib
import html
import json
import os
import re
import sys
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BASE = 'https://egy.voxcinemas.com'
STATE = Path('state.enc')
EXPECTED_BOT = 'VoxCinemasAlertsBot'

_request_lock = threading.Lock()
_last_request = 0.0


def get_page(url):
    global _last_request
    for attempt in range(3):
        with _request_lock:
            time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_request)))
            _last_request = time.monotonic()
        request = urllib.request.Request(url, headers={
            'User-Agent': 'VOXCinemasAlertsBot/1.0 (+https://github.com/mostafabrowsing-dot/vox-cinemas-alerts)',
            'Accept': 'text/html',
        })
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.read().decode('utf-8')
        except urllib.error.HTTPError as error:
            if error.code not in (403, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(3 * (attempt + 1))


def clean(value):
    return html.unescape(re.sub('<[^>]+>', '', value)).strip()

def added_booking_dates(previous, movie):
    known = previous.get('listed_dates', previous.get('dates', []))
    return sorted(set(movie.get('dates', [])) - set(known))

def selected_booking_date(page):
    for tag in re.findall(r'<input\b[^>]*>', page, re.I):
        attrs = dict(re.findall(r'([\w-]+)\s*=\s*["\']([^"\']*)["\']', tag))
        if attrs.get('name') == 'd' and re.fullmatch(r'\d{8}', attrs.get('value', '')):
            value = attrs['value']
            datetime.strptime(value, '%Y%m%d')
            return value
    raise ValueError('Booking page does not declare its selected date')

def booking_dates(dates):
    today = datetime.now(ZoneInfo('Africa/Cairo')).date()
    weekdays = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    labels = []
    for value in sorted(set(dates)):
        date = datetime.strptime(value, '%Y%m%d').date()
        distance = (date - today).days
        if distance == 0:
            labels.append('Today')
        elif distance == 1:
            labels.append('Tomorrow')
        else:
            labels.append(f'{weekdays[date.weekday()]} {date.day} {months[date.month - 1]}')
    return ' | '.join(labels)

def telegram(token, method, payload):
    req = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method,
                                 data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.load(r)
        if not data.get('ok'):
            raise RuntimeError('Telegram request rejected')
        return data['result']
    except Exception:
        raise RuntimeError('Telegram request failed; check token and bot permissions') from None

def deliver(token, chat_id, item):
    if isinstance(item, str):
        return telegram(token, 'sendMessage', {'chat_id': chat_id, 'text': item, 'disable_web_page_preview': True})
    markup = {'inline_keyboard': [[{'text': 'Book tickets', 'url': item['url']}]]}
    caption = item['caption']
    if item.get('photo') and len(caption) <= 1024:
        try:
            return telegram(token, 'sendPhoto', {'chat_id': chat_id, 'photo': item['photo'], 'caption': caption, 'parse_mode': 'HTML', 'reply_markup': markup})
        except RuntimeError:
            print('Photo delivery failed; trying text card.')
    return telegram(token, 'sendMessage', {'chat_id': chat_id, 'text': caption, 'parse_mode': 'HTML', 'reply_markup': markup, 'disable_web_page_preview': True})

def attrs(tag):
    return dict(re.findall(r'''([\w-]+)\s*=\s*["']([^"']*)["']''', tag))


def cinema_url(cinema, **query):
    return BASE + '/showtimes?' + urllib.parse.urlencode({'c': cinema['id'], **query})


def discover(page):
    cinemas = {}
    for label in re.findall(r'<label\b[^>]*>.*?</label>', page, re.S):
        for tag in re.findall(r'<input\b[^>]*>', label):
            a = attrs(tag)
            if a.get('name') != 'c':
                continue
            key = a.get('value', '')
            name = clean(re.sub(r'<input\b[^>]*>', '', label)).strip()
            if not re.fullmatch(r'[a-z0-9-]+', key) or not name:
                raise ValueError('Invalid cinema filter')
            cinemas[key] = {'id': key, 'name': name}
    if not cinemas:
        raise ValueError('Cinema filters missing')
    return cinemas


def parse_page(page, cinema):
    """Only parse sessions inside the matching h3 block, even on unfiltered pages."""
    movies = {}
    for article in re.findall(r'<article\b[^>]*class="movie-compare"[^>]*>.*?</article>', page, re.S):
        a = attrs(article.split('>')[0])
        title = re.search(r'<h2\b[^>]*>(.*?)</h2>', article, re.S)
        if not a.get('data-slug') or not title:
            continue
        blocks = re.split(r'<h3\b[^>]*>(.*?)</h3>', article, flags=re.S)
        formats, listed = set(), False
        for i in range(1, len(blocks), 2):
            if clean(blocks[i]) != cinema['name']:
                continue
            listed = True
            current_format = None
            for t in re.finditer(r'<strong\b[^>]*>(.*?)</strong>|<a\b([^>]*)>(.*?)</a>', blocks[i+1], re.S):
                if t[1] is not None:
                    current_format = clean(t[1])
                else:
                    href = attrs(t[2]).get('href', '')
                    parsed = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, html.unescape(href)))
                    if parsed.netloc == 'egy.voxcinemas.com' and parsed.path.startswith('/booking/'):
                        if not current_format:
                            raise ValueError('Booking format missing')
                        formats.add(current_format)
        if listed:
            movies[a['data-slug']] = {'title': clean(title[1]), 'formats': sorted(formats)}
    if not movies:
        # VOX can list a date in the calendar even when that cinema has no shows.
        selected = []
        for tag in re.findall(r'<input\b[^>]*>', page, re.I):
            values = attrs(tag)
            if values.get('name') == 'c' and values.get('type') == 'hidden':
                selected.append(values.get('value'))
        empty = re.search(
            r'<p class="message none">\s*No showtimes could be found for your current cinema\(s\), movie\(s\) and date\.',
            page,
        )
        if empty and selected == [cinema['id']]:
            return {}
        raise ValueError('No matching cinema movie blocks; previous state retained')
    return movies


def collect(cinema):
    page = get_page(cinema_url(cinema))
    today = datetime.now(ZoneInfo('Africa/Cairo')).strftime('%Y%m%d')
    default = selected_booking_date(page)
    if default < today:
        # VOX may keep yesterday selected shortly after Cairo midnight.
        page = get_page(cinema_url(cinema, d=today))
        default = selected_booking_date(page)
        if default != today:
            raise ValueError('Returned date does not match requested date')
    pending, done, result = {default}, set(), {}
    def read(date):
        content = page if date == default else get_page(cinema_url(cinema, d=date))
        if selected_booking_date(content) != date:
            raise ValueError('Returned date does not match requested date')
        return date, content, parse_page(content, cinema)
    # Branches run sequentially; this is the single global pool (at most 3 requests).
    with ThreadPoolExecutor(max_workers=3) as pool:
        while pending:
            batch = sorted(pending - done)
            pending = set()
            for date, content, movies in pool.map(read, batch):
                done.add(date)
                for href in re.findall(r'href=["\']([^"\']+)["\']', content):
                    parsed = urllib.parse.urlsplit(urllib.parse.urljoin(BASE, html.unescape(href)))
                    q = urllib.parse.parse_qs(parsed.query)
                    if parsed.netloc != 'egy.voxcinemas.com' or parsed.path != '/showtimes' or q.get('c') != [cinema['id']]:
                        continue
                    for d in q.get('d', []):
                        if re.fullmatch(r'\d{8}', d) and d >= today and d not in done:
                            datetime.strptime(d, '%Y%m%d')
                            pending.add(d)
                for slug, item in movies.items():
                    movie = result.setdefault(slug, {'title': item['title'], 'dates': [], 'listed_dates': [], 'formats_by_date': {}})
                    movie['listed_dates'].append(date)
                    movie['formats_by_date'][date] = item['formats']
                    if item['formats']:
                        movie['dates'].append(date)
            pending -= done
    for movie in result.values():
        movie['dates'].sort()
        movie['listed_dates'].sort()
    return result


def merge_seen(previous, movie):
    return {'title': movie['title'],
            'dates': sorted(set(previous.get('dates', []) + movie['dates'])),
            'listed_dates': sorted(set(previous.get('listed_dates', previous.get('dates', [])) + movie['listed_dates']))}


def make_card(cinema, slug, movie, dates, test=False):
    poster = None
    try:
        page = get_page(BASE + '/movies/' + urllib.parse.quote(slug, safe=''))
        match = re.search(r'https://assets\.voxcinemas\.com/posters/[^"\s<>]+', page)
        if match:
            poster = html.unescape(match[0])
    except Exception:
        print('Poster unavailable; using text.')
    formats = sorted({f for d in dates for f in movie['formats_by_date'].get(d, [])})
    caption = '🧪 TEST — Preview only; this is not a new booking alert.\n\n' if test else ''
    caption += (f"<b>Movie: {html.escape(movie['title'])}</b>\nVOX Cinemas | {html.escape(cinema['name'])}\n\n"
                f"<b>Booking dates</b>\n{html.escape(booking_dates(dates))}\n\n"
                f"<b>Formats with booking links</b>\n{html.escape(' | '.join(formats))}\n\nSeat availability is not verified.")
    return {'photo': poster, 'caption': caption, 'url': cinema_url(cinema, m=slug)}


def changes(cinema, old, current):
    return [make_card(cinema, slug, movie, added)
            for slug, movie in current.items()
            if (added := added_booking_dates(old.get(slug, {}), movie))]


def apply_scan(state, cinema, current=None):
    branch = state['cinemas'].setdefault(cinema['id'], {'seen': {}, 'initialized': False})
    branch['name'] = cinema['name']
    notice, events = None, []
    if current is None:
        branch['failures'] = branch.get('failures', 0) + 1
        branch['counts'] = None
        if branch['failures'] >= 3 and not branch.get('alerted'):
            branch['alerted'] = True
            notice = f"⚠️ VOX | {cinema['name']}: 3 consecutive checks failed. Previous listings retained; retrying automatically."
    else:
        if branch.get('alerted'):
            notice = f"✅ VOX | {cinema['name']}: monitoring restored."
        ready = branch['initialized']
        old = branch['seen']
        events = changes(cinema, old, current) if ready else []
        branch['counts'] = {
            'movies': len(current),
            'new_movies': sum(bool(m['dates']) and slug not in old for slug, m in current.items()) if ready else 0,
            'new_dates': sum(len(added_booking_dates(old[slug], m)) for slug, m in current.items() if slug in old) if ready else 0,
        }
        for slug, movie in current.items():
            old[slug] = merge_seen(old.get(slug, {}), movie)
        branch.update(initialized=True, failures=0, alerted=False,
                      last_success=datetime.now(ZoneInfo('Africa/Cairo')).strftime('%d %b %Y, %H:%M'))
    for pending in state['subscribers'].values():
        pending.extend(events)
        if notice:
            pending.append(notice)
    return events


def status_text(state):
    branches = state['cinemas']
    healthy = bool(branches) and not state.get('discovery_error') and all(not b.get('failures', 0) and b.get('initialized') for b in branches.values())
    lines = ['🎬 VOX Cinemas Alerts | Monitoring Status', 'Overall: ' + ('Operational' if healthy else 'Update delayed / awaiting successful checks')]
    if state.get('discovery_error'):
        lines.append('Cinema discovery unavailable; known branches retained.')
    for b in branches.values():
        counts = b.get('counts') or {}
        lines.extend(['', b['name'], 'Last success: ' + b.get('last_success', 'None') + ' (Cairo)',
                      f"Consecutive failed checks: {b.get('failures', 0)}",
                      f"Movies checked: {counts.get('movies', 'N/A')}",
                      f"Newly bookable movies: {counts.get('new_movies', 'N/A')}",
                      f"New dates for existing movies: {counts.get('new_dates', 'N/A')}"])
    lines.extend(['', 'Counts refer to this check only.', 'Checks are requested every minute; processing may be delayed.'])
    return '\n'.join(lines)


def new_state():
    return {'version': 1, 'offset': 0, 'subscribers': {}, 'cinemas': {}, 'replies': {}, 'tests': []}


def deliver_tests(token, state, cinemas, current_by_branch):
    """One TEST per cinema, remembering successful deliveries across retries."""
    progress = state.setdefault('test_progress', {})
    for target in list(state['tests']):
        request = progress.get(target)
        if request is None:
            if state.get('discovery_error') or not cinemas:
                continue
            request = {'remaining': list(cinemas)}
            progress[target] = request
        for key in list(request['remaining']):
            if key not in cinemas or key not in current_by_branch:
                continue
            example = next(((slug, movie) for slug, movie in current_by_branch[key].items()
                            if movie['dates']), None)
            if example is None:
                continue
            slug, movie = example
            try:
                card = make_card(cinemas[key], slug, movie, movie['dates'], test=True)
                deliver(token, target, card)
                request['remaining'].remove(key)
                print('Requested TEST delivered:', cinemas[key]['name'])
            except Exception:
                print('TEST pending:', cinemas[key]['name'])
        if not request['remaining']:
            state['tests'].remove(target)
            progress.pop(target, None)


def main():
    check = '--check' in sys.argv
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not check and not token:
        print('Waiting for TELEGRAM_BOT_TOKEN; no messages sent.')
        return
    if check:
        state = new_state()
    else:
        from cryptography.fernet import Fernet
        cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest()))
        identity = telegram(token, 'getMe', {})
        if identity.get('username', '').casefold() != EXPECTED_BOT.casefold():
            raise ValueError('Unexpected bot identity')
        if telegram(token, 'getWebhookInfo', {}).get('url'):
            raise ValueError('Webhook active; remove it before using this polling deployment')
        state = json.loads(cipher.decrypt(STATE.read_bytes())) if STATE.exists() else new_state()
        for update in telegram(token, 'getUpdates', {'offset': state['offset'], 'timeout': 0, 'allowed_updates': ['message']}):
            msg = update.get('message', {})
            chat = msg.get('chat', {})
            command = msg.get('text', '').split(' ')[0].split('@')[0]
            if chat.get('type') == 'private':
                key = str(chat['id'])
                if command == '/start':
                    state['subscribers'].setdefault(key, [])
                    state['replies'][key] = "🎬 Welcome to VOX Cinemas Alerts Bot !\n\nYou’re now subscribed to booking alerts for VOX Cinemas Egypt.\n\n🍿 New movie bookings & pre-bookings\n📅 Newly available booking dates\n🎟 Movie posters, available formats & booking links\n\n/status — View monitoring status\n/stop — Pause notifications\n\nChecks are requested every minute; notifications may be delayed."
                elif command == '/stop':
                    state['subscribers'].pop(key, None)
                    if key in state['tests']:
                        state['tests'].remove(key)
                    state.setdefault('test_progress', {}).pop(key, None)
                    state['replies'][key] = "🔕 Notifications paused\n\nYou’re no longer subscribed to booking alerts for VOX Cinemas Egypt.\n\nSend /start whenever you’re ready to receive alerts again."
                elif command == '/status':
                    state['replies'][key] = None
                elif command == '/test' and key not in state['tests']:
                    state['tests'].append(key)
                    state.setdefault('test_progress', {}).pop(key, None)
            state['offset'] = max(state['offset'], update['update_id'] + 1)
    current_by_branch = {}
    try:
        cinemas = discover(get_page(BASE + '/showtimes'))
        missing = set(state['cinemas']) - set(cinemas)
        state['discovery_error'] = bool(missing)
        for key in missing:
            apply_scan(state, {'id': key, 'name': state['cinemas'][key]['name']})
    except Exception as error:
        print('Cinema discovery failed:', type(error).__name__)
        state['discovery_error'] = True
        cinemas = {key: {'id': key, 'name': b['name']} for key, b in state['cinemas'].items()}
    for cinema in cinemas.values():
        try:
            current = collect(cinema)
            apply_scan(state, cinema, current)
            current_by_branch[cinema['id']] = current
            print(cinema['name'], json.dumps(state['cinemas'][cinema['id']]['counts']))
        except Exception as error:
            print(cinema['name'], 'scan failed:', type(error).__name__, str(error)[:160])
            apply_scan(state, cinema)
    if check:
        if not cinemas or state['discovery_error'] or any(b.get('failures') for b in state['cinemas'].values()):
            raise RuntimeError('Live check incomplete')
        print('All discovered cinema checks passed. No messages sent.')
        return
    deliver_tests(token, state, cinemas, current_by_branch)
    for target, reply in list(state['replies'].items()):
        try:
            telegram(token, 'sendMessage', {'chat_id': target, 'text': reply if reply is not None else status_text(state)})
            del state['replies'][target]
        except RuntimeError:
            print('Command reply pending.')
    for target, pending in state['subscribers'].items():
        while pending:
            try:
                deliver(token, target, pending[0])
                pending.pop(0)
            except RuntimeError:
                print('Notification pending.')
                break
    temporary = STATE.with_suffix('.tmp')
    temporary.write_bytes(cipher.encrypt(json.dumps(state, ensure_ascii=False).encode()))
    temporary.replace(STATE)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Monitor failed safely:', type(error).__name__)
        sys.exit(1)
