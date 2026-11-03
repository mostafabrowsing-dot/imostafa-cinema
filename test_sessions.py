import unittest
from unittest.mock import patch
import bot as b

class SessionTests(unittest.TestCase):
    def test_session_parser(self):
        page = '<article class="movie-compare" data-slug="film"><h3>City Centre Almaza</h3><strong>GOLD</strong><a href="/booking/one">12:30am </a><a href="/booking/two">12:30pm</a><strong>Standard</strong><a href="/booking/three">12:30pm</a></article>'
        items = b.parse_sessions(page)['film']
        self.assertEqual(len(items), 3)
        self.assertEqual(items['gold|30']['minutes'], 30)
        self.assertEqual(items['gold|750']['minutes'], 750)
        self.assertIn('standard|750', items)

    def test_migration_new_time_and_dedup(self):
        session = {'time': '8:30pm', 'minutes': 1230, 'format': 'GOLD'}
        movie = {'title': 'Film', 'dates': ['20261217'], 'sessions_by_date': {'20261217': {'gold|1230': session}}}
        legacy = {'title': 'Film', 'dates': ['20261217']}
        self.assertEqual(b.new_session_entries(legacy, movie), [])
        old = b.merge_seen(legacy, movie)
        movie['sessions_by_date']['20261217']['gold|1350'] = {'time': '10:30pm', 'minutes': 1350, 'format': 'GOLD'}
        entries = b.new_session_entries(old, movie)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['time'], '10:30pm')
        with patch.object(b, 'get_page', return_value=''):
            events = b.make_time_cards('film', movie, entries)
            self.assertEqual(b.changes({'film': old}, {'film': movie}), [])
        self.assertEqual(len(events), 1)
        self.assertIn('New showtime added', events[0]['caption'])
        self.assertIn('10:30pm', events[0]['caption'])
        merged = b.merge_seen(old, movie)
        self.assertEqual(b.new_session_entries(merged, movie), [])
        # Disappearing/reappearing sessions retain their identity.
        self.assertIn('gold|1350', b.merge_seen(merged, {'title':'Film','dates':['20261217'],'sessions_by_date':{'20261217':{}}})['sessions_by_date']['20261217'])

    def test_new_day_not_double_counted(self):
        movie = {'title':'Film','dates':['20261218'],'sessions_by_date':{'20261218':{'gold|600':{'time':'10:00am','minutes':600,'format':'GOLD'}}}}
        self.assertEqual(b.new_session_entries({'dates':['20261217'],'sessions_by_date':{'20261217':{}}},movie),[])

if __name__ == '__main__':
    unittest.main()
