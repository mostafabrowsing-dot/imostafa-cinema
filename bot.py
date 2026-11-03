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
        return date, parse_movies(page if date == today else get_page(URL + '&d=' + date))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for date, movies in pool.map(read_date, sorted(dates)):
            for slug, title in movies.items():
                movie = result.setdefault(slug, {'title': title, 'dates': []})
                movie['dates'].append(date)
    if not result:
        raise ValueError('No bookable movies; keeping previous state')
    return result

def changes(old, current):
    events = []
    for slug, movie in current.items():
        added = sorted(set(movie['dates']) - set(old.get(slug, {}).get('dates', [])))
        if added:
            label = '🎬 فتح حجز فيلم في ألماظة' if slug not in old else '📅 أيام حجز جديدة في ألماظة'
            dates = ', '.join(datetime.strptime(d, '%Y%m%d').strftime('%d/%m/%Y') for d in added)
            events.append(f"{label}\n{movie['title']}\n{dates}\n{URL}&m={urllib.parse.quote(slug)}")
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
        events = changes(state['seen'], current) if state['initialized'] else []
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
        last = state.get('last_success', 'لم يسجل بعد')
        count = state.get('scan_failures', 0)
        text = f'🎬 VOX ألماظة\nآخر فحص ناجح بتوقيت مصر: {last}\nفحوصات فاشلة متتالية: {count}\nالوقت المعروض يشمل نتيجة الفحص في هذا التشغيل. قد يتأخر بدء التشغيل.'
        try:
            telegram(token, 'sendMessage', {'chat_id': chat_id, 'text': text})
            status_requests.remove(chat_id)
        except RuntimeError:
            print('Status reply pending; will retry next run.')
    for chat_id, pending in state['subscribers'].items():
        while pending:
            try:
                telegram(token, 'sendMessage', {'chat_id': chat_id, 'text': pending[0], 'disable_web_page_preview': True})
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
