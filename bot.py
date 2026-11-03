import base64
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = 'https://egy.voxcinemas.com'
URL = BASE + '/showtimes?c=city-centre-almaza'
STATE = Path('state.enc')

def get_page(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read().decode('utf-8')

def clean(value):
    return html.unescape(re.sub('<[^>]+>', '', value)).strip()

def parse_movies(page):
    if 'City Centre Almaza' not in page:
        raise ValueError('Almaza page missing')
    result = {}
    for article in re.findall(r'<article\b[^>]*class="movie-compare"[^>]*>.*?</article>', page, re.S):
        slug = re.search(r'data-slug="([^"]+)"', article)
        title = re.search(r'<h2\b[^>]*>(.*?)</h2>', article, re.S)
        if slug and title and '/booking/' in article and re.search(r'<h3[^>]*>\s*City Centre Almaza\s*</h3>', article):
            result[slug[1]] = clean(title[1])
    return result

def collect():
    page = get_page(URL)
    today = datetime.now(ZoneInfo('Africa/Cairo')).strftime('%Y%m%d')
    dates = {today}
    for href in re.findall(r'href="([^"]+)"', page):
        href = html.unescape(href)
        if href.startswith('/showtimes?'):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(href).query)
            if query.get('c') == ['city-centre-almaza']:
                dates.update(d for d in query.get('d', []) if re.fullmatch(r'\d{8}', d) and d >= today)
    result = {}
    def read_date(date):
        current_page = page if date == today else get_page(URL + '&d=' + date)
        return date, parse_movies(current_page), parse_formats(current_page)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for date, movies, formats in pool.map(read_date, sorted(dates)):
            for slug, title in movies.items():
                movie = result.setdefault(slug, {'title': title, 'dates': []})
                movie['dates'].append(date)
                movie.setdefault('formats_by_date', {})[date] = formats.get(slug, [])
    if not result:
        raise ValueError('No bookable movies; keeping previous state')
    return result


def parse_formats(page):
    result = {}
    for article in re.findall(r'<article\b[^>]*class="movie-compare"[^>]*>.*?</article>', page, re.S):
        slug = re.search(r'data-slug="([^"]+)"', article)
        if slug:
            result[slug[1]] = sorted(set(clean(x) for x in re.findall(r'<strong\b[^>]*>(.*?)</strong>', article, re.S)))
    return result

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


def make_card(slug, movie, dates, test=False):
    poster = None
    try:
        page = get_page(BASE + '/movies/' + urllib.parse.quote(slug))
        match = re.search(r'https://assets\.voxcinemas\.com/posters/[^"\s<>]+', page)
        if match:
            poster = html.unescape(match[0])
    except Exception:
        print('Poster unavailable; using text card.')
    formats = sorted({f for d in dates for f in movie.get('formats_by_date', {}).get(d, [])})
    title = html.escape(movie['title'])
    date_text = html.escape(booking_dates(dates))
    format_text = html.escape(' | '.join(formats) or 'See booking page')
    caption = ('🧪 TEST — رسالة تجريبية وليست فتح حجز جديد\n\n' if test else '')
    caption += f'<b>Movie: {title}</b>\nVOX Cinemas | City Centre Almaza\n\n<b>Booking dates</b>\n{date_text}\n\n<b>Available formats</b>\n{format_text}'
    return {'photo': poster, 'caption': caption, 'url': URL + '&m=' + urllib.parse.quote(slug)}

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


def changes(old, current):
    events = []
    for slug, movie in current.items():
        added = sorted(set(movie['dates']) - set(old.get(slug, {}).get('dates', [])))
        if added:
            events.append(make_card(slug, movie, added))
    return events

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

def update_health(state, success):
    failures = state.get('scan_failures', 0)
    notice = None
    if success:
        if state.get('scan_alerted', False):
            notice = '✅ متابعة مواعيد VOX ألماظة رجعت تشتغل.'
        state['scan_failures'] = 0
        state['scan_alerted'] = False
        state['last_success'] = datetime.now(ZoneInfo('Africa/Cairo')).strftime('%d/%m/%Y %H:%M')
    else:
        state['scan_failures'] = failures + 1
        if state['scan_failures'] >= 3 and not state.get('scan_alerted', False):
            notice = '⚠️ تعذر تحديث مواعيد VOX ألماظة في 3 فحوصات متتالية. آخر مواعيد محفوظة كما هي؛ هنحاول تلقائيًا ونبلغك لما المتابعة ترجع.'
            state['scan_alerted'] = True
    if notice:
        for pending in state['subscribers'].values():
            pending.append(notice)

def main():
    if '--check' in sys.argv:
        current = collect()
        print(json.dumps(current, ensure_ascii=False, indent=2))
        return
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        print('Waiting for TELEGRAM_BOT_TOKEN secret; no notifications sent.')
        return
    identity = telegram(token, 'getMe', {})
    print('Connected bot: @' + identity.get('username', 'unknown'))
    from cryptography.fernet import Fernet
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(token.encode()).digest()))
    state = json.loads(cipher.decrypt(STATE.read_bytes())) if STATE.exists() else {'offset': 0, 'subscribers': {}, 'seen': {}, 'initialized': False}
    updates = telegram(token, 'getUpdates', {'offset': state['offset'], 'timeout': 0, 'allowed_updates': ['message']})
    print(f'Telegram updates received: {len(updates)}')
    for update in updates:
        message = update.get('message', {})
        chat = message.get('chat', {})
        command = message.get('text', '').split(' ')[0].split('@')[0]
        if chat.get('type') == 'private':
            key = str(chat['id'])
            if command == '/start':
                state['subscribers'].setdefault(key, [])
                telegram(token, 'sendMessage', {'chat_id': key, 'text': 'أهلًا بيك في iMostafa Cinema 🎬\nتم الاشتراك في تنبيهات كل أفلام VOX ألماظة: فتح الحجز والحجز المسبق وأيام الحجز الجديدة.\n/stop لإيقاف التنبيهات.\nالتحديثات دورية وقد تتأخر.'})
            elif command == '/test':
                requests = state.setdefault('test_requests', [])
                if key not in requests:
                    requests.append(key)
            elif command == '/status':
                requests = state.setdefault('status_requests', [])
                if key not in requests:
                    requests.append(key)
            elif command == '/stop':
                state['subscribers'].pop(key, None)
                telegram(token, 'sendMessage', {'chat_id': key, 'text': 'تم إيقاف التنبيهات. للرجوع ابعت /start'})
        state['offset'] = max(state['offset'], update['update_id'] + 1)
    print(f'Active subscribers: {len(state["subscribers"])}')
    try:
        current = collect()
        for target in list(state.get('test_requests', [])):
            if 'dune-part-three' in current:
                item = make_card('dune-part-three', current['dune-part-three'], current['dune-part-three']['dates'], test=True)
            else:
                slug = next(iter(current))
                item = make_card(slug, current[slug], current[slug]['dates'], test=True)
            try:
                deliver(token, target, item)
                state['test_requests'].remove(target)
                print('Requested test card delivered.')
            except RuntimeError:
                print('Test card pending; will retry next run.')
        events = changes(state['seen'], current) if state['initialized'] else []
        state['last_scan_counts'] = {
            'movies_checked': len(current),
            'new_movies': sum(slug not in state['seen'] for slug in current) if state['initialized'] else 0,
            'added_dates': sum(len(set(movie['dates']) - set(state['seen'][slug].get('dates', []))) for slug, movie in current.items() if slug in state['seen']) if state['initialized'] else 0,
        }
        for slug, movie in current.items():
            previous = state['seen'].get(slug, {}).get('dates', [])
            state['seen'][slug] = {'title': movie['title'], 'dates': sorted(set(previous + movie['dates']))}
        state['initialized'] = True
        for pending in state['subscribers'].values():
            pending.extend(events)
        update_health(state, True)
        print(f'Checked {len(current)} movies; {len(events)} new notifications.')
    except Exception:
        update_health(state, False)
        print('VOX check failed; previous listings preserved. Next scheduled run will retry.')
    status_requests = state.setdefault('status_requests', [])
    for chat_id in list(status_requests):
        last = state.get('last_success')
        count = state.get('scan_failures', 0)
        try:
            last_display = datetime.strptime(last, '%d/%m/%Y %H:%M').strftime('%d %b %Y, %H:%M') if last else 'No successful check yet'
        except (ValueError, TypeError):
            last_display = 'Unavailable'
        metrics = state.get('last_scan_counts', {})
        valid_counts = last is not None and count == 0 and bool(metrics)
        movies_checked = metrics.get('movies_checked', 'N/A') if valid_counts else 'N/A'
        new_movies = metrics.get('new_movies', 'N/A') if valid_counts else 'N/A'
        added_dates = metrics.get('added_dates', 'N/A') if valid_counts else 'N/A'
        health = 'Operational' if last and count == 0 else 'Awaiting first successful check' if not last else 'Update delayed — retrying'
        text = (
            '🎬 iMostafa Cinema | Monitoring Status\n'
            'VOX Cinemas • City Centre Almaza\n\n'
            f'Status: {health}\n'
            f'Last successful check: {last_display} (Cairo)\n'
            f'Consecutive failed checks: {count}\n\n'
            f'Movies checked: {movies_checked}\n'
            f'Newly bookable movies: {new_movies}\n'
            f'New booking dates for existing movies: {added_dates}\n'
            'Counts refer to this check only.\n\n'
            'Checks are requested every minute; processing may be delayed.'
        )
        try:
            telegram(token, 'sendMessage', {'chat_id': chat_id, 'text': text})
            status_requests.remove(chat_id)
        except RuntimeError:
            print('Status reply pending; will retry next run.')
    for chat_id, pending in state['subscribers'].items():
        while pending:
            try:
                deliver(token, chat_id, pending[0])
                pending.pop(0)
            except RuntimeError:
                print('Delivery pending; will retry next run.')
                break
    STATE.write_bytes(cipher.encrypt(json.dumps(state, ensure_ascii=False).encode()))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Bot failed safely (' + type(error).__name__ + '); state not overwritten.')
        sys.exit(1)
