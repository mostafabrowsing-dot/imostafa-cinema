import copy
import unittest
from unittest.mock import patch
import bot as b

A = {'id': 'city-centre-almaza', 'name': 'City Centre Almaza'}
B = {'id': 'mall-of-egypt', 'name': 'Mall of Egypt'}
C = {'id': 'city-centre-alexandria', 'name': 'City Centre Alexandria'}

def movie(dates=('20261216',), listed=None, fmt='GOLD'):
    return {'title': 'Film', 'dates': list(dates), 'listed_dates': list(dates if listed is None else listed), 'formats_by_date': {d: [fmt] for d in dates}}

def page(date='20261216', extra=''):
    return f'<input name="d" value="{date}">' + extra + '<article class="movie-compare" data-slug="film"><h2>Film</h2><h3>City Centre Almaza</h3><strong>GOLD</strong><a href="/booking/1">3:30pm</a><h3>Mall of Egypt</h3><strong>IMAX</strong><a href="/booking/2">4:30pm</a></article>'

class Tests(unittest.TestCase):
    def setUp(self):
        self.poster = patch.object(b, 'get_page', return_value='')
        self.poster.start()
        self.addCleanup(self.poster.stop)

    def test_discovery_reads_real_values(self):
        self.assertEqual(b.discover('<label><input name="c" value="actual-filter"><span>Actual Name</span></label>'), {'actual-filter': {'id':'actual-filter','name':'Actual Name'}})
        with self.assertRaises(ValueError): b.discover('challenge')

    def test_branch_parser_formats_are_isolated(self):
        self.assertEqual(b.parse_page(page(), A)['film']['formats'], ['GOLD'])
        self.assertEqual(b.parse_page(page(), B)['film']['formats'], ['IMAX'])
        with self.assertRaises(ValueError): b.parse_page(page(), C)

    def test_sold_out_remains_listed(self):
        p=page().replace('<a href="/booking/1">3:30pm</a>', '<span class="showtime unavailable">3:30pm</span>')
        self.assertEqual(b.parse_page(p,A)['film']['formats'], [])

    def test_silent_baselines_new_branch_and_isolated_event(self):
        state=b.new_state(); state['subscribers']['1']=[]
        for c in (A,B,C): self.assertEqual(b.apply_scan(state,c,{'film':movie()}), [])
        self.assertEqual(state['subscribers']['1'], [])
        before=copy.deepcopy(state['cinemas'][B['id']])
        current={'film':movie(('20261216','20261217'))}
        events=b.apply_scan(state,A,current)
        self.assertEqual(len(events),1)
        self.assertIn(A['name'],events[0]['caption'])
        self.assertIn(A['id'],events[0]['url'])
        self.assertNotIn('IMAX',events[0]['caption'])
        self.assertEqual(state['cinemas'][B['id']],before)
        self.assertEqual(b.apply_scan(state,A,current),[])

    def test_returning_old_day_and_changed_time_or_format_are_silent(self):
        old={'film':movie(('20261216',),('20261216','20261217'))}
        current={'film':movie(('20261216','20261217'),fmt='IMAX')}
        self.assertEqual(b.changes(A,old,current),[])
        merged=b.merge_seen(old['film'],current['film'])
        merged=b.merge_seen(merged,movie((),()))
        self.assertEqual(b.added_booking_dates(merged,current['film']),[])

    def test_failure_preserves_seen_and_other_branches_update(self):
        s=b.new_state();s['subscribers']['1']=[]
        for c in (A,B,C):b.apply_scan(s,c,{'film':movie()})
        old=copy.deepcopy(s['cinemas'][A['id']]['seen'])
        for _ in range(3):b.apply_scan(s,A)
        for c in (B,C):b.apply_scan(s,c,{'film':movie(('20261216','20261217'))})
        self.assertEqual(s['cinemas'][A['id']]['seen'],old)
        self.assertEqual(s['cinemas'][A['id']]['failures'],3)
        self.assertIn('N/A',b.status_text(s))
        self.assertIn(A['name'],s['subscribers']['1'][0])
        b.apply_scan(s,A,{'film':movie()})
        self.assertIn('restored',s['subscribers']['1'][-1])

    def test_rollover_uses_page_date_and_far_future_days(self):
        default=page('20261216','<a href="/showtimes?c=city-centre-almaza&amp;d=20261223">Later</a>')
        with patch.object(b,'get_page',side_effect=lambda url: page('20261223') if 'd=20261223' in url else default):
            self.assertEqual(b.collect(A)['film']['dates'],['20261216','20261223'])

    def test_confirmed_empty_day_keeps_other_dates(self):
        link = '<a href="/showtimes?c=city-centre-almaza&amp;d=20261223">Later</a>'
        empty = (
            '<input name="d" value="20261216">'
            '<input type="hidden" name="c" value="city-centre-almaza">'
            '<p class="message none">No showtimes could be found for your current '
            'cinema(s), movie(s) and date. Please amend your selection and try again.</p>'
            + link
        )
        with patch.object(b, 'get_page', side_effect=[empty, page('20261223')]):
            self.assertEqual(b.collect(A)['film']['dates'], ['20261223'])
        with self.assertRaises(ValueError):
            b.parse_page(empty, B)

    def test_wrong_explicit_date_rejected(self):
        default=page('20261216','<a href="/showtimes?c=city-centre-almaza&amp;d=20261223">Later</a>')
        with patch.object(b,'get_page',return_value=default):
            with self.assertRaisesRegex(ValueError,'does not match'):b.collect(A)

    def test_stale_default_retries_with_cairo_date(self):
        today = b.datetime.now(b.ZoneInfo('Africa/Cairo')).strftime('%Y%m%d')
        with patch.object(b, 'get_page', side_effect=[page('20000101'), page(today)]) as fetch:
            self.assertEqual(b.collect(A)['film']['dates'], [today])
            self.assertEqual(fetch.call_args.args, (b.cinema_url(A, d=today),))

    def test_stale_default_rejected_if_retry_is_still_stale(self):
        with patch.object(b,'get_page',return_value=page('20000101')):
            with self.assertRaisesRegex(ValueError,'does not match'):b.collect(A)

    def test_test_card_does_not_change_movie(self):
        m=movie();before=copy.deepcopy(m)
        card=b.make_card(B,'film',m,m['dates'],test=True)
        self.assertIn('TEST',card['caption']);self.assertIn(B['id'],card['url'])
        self.assertEqual(m,before)

    def test_test_is_only_sent_to_requesting_chat(self):
        import tempfile
        from pathlib import Path
        from cryptography.fernet import Fernet
        calls=[]
        def telegram(token,method,payload):
            calls.append((method,payload))
            if method=='getMe':return {'username':b.EXPECTED_BOT}
            if method=='getWebhookInfo':return {'url':''}
            if method=='getUpdates':return [{'update_id':1,'message':{'chat':{'id':123,'type':'private'},'text':'/test'}}]
            return {}
        with tempfile.TemporaryDirectory() as d:
            state=b.new_state();state['subscribers']['456']=[]
            cipher=Fernet(b.base64.urlsafe_b64encode(b.hashlib.sha256(b'test-token').digest()))
            path=Path(d)/'state.enc';path.write_bytes(cipher.encrypt(b.json.dumps(state).encode()))
            with patch.object(b,'STATE',path),patch.dict(b.os.environ,{'TELEGRAM_BOT_TOKEN':'test-token'}),patch.object(b,'telegram',side_effect=telegram),patch.object(b,'discover',return_value={A['id']:A}),patch.object(b,'collect',return_value={'film':movie()}),patch.object(b.sys,'argv',['bot.py']):b.main()
        sent=[payload for method,payload in calls if method in ('sendMessage','sendPhoto')]
        self.assertEqual(len(sent),1);self.assertEqual(sent[0]['chat_id'],'123');self.assertIn('TEST',sent[0].get('text',''))

if __name__=='__main__':unittest.main()
