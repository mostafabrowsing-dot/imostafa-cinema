import unittest
from unittest.mock import patch
import bot as b

class BookingDateTests(unittest.TestCase):
    def test_unavailable_date_reopening_is_not_new(self):
        previous = {'title':'Film','dates':['20261216'],'listed_dates':['20261216','20261217']}
        movie = {'title':'Film','dates':['20261216','20261217'],'listed_dates':['20261216','20261217']}
        self.assertEqual(b.added_booking_dates(previous, movie), [])
        with patch.object(b, 'get_page', return_value=''):
            self.assertEqual(b.changes({'film':previous},{'film':movie}), [])
        movie['dates'].append('20261218')
        movie['listed_dates'].append('20261218')
        self.assertEqual(b.added_booking_dates(previous, movie), ['20261218'])
        self.assertEqual(b.added_booking_dates(b.merge_seen(previous,movie), movie), [])

    def test_closed_movie_and_formats_remain_known(self):
        page = '<article class="movie-compare" data-slug="film"><h2>Film</h2><h3>City Centre Almaza</h3><strong>GOLD</strong><a href="/booking/1">3:30pm</a><strong>Standard</strong><span class="action showtime unavailable">3:30pm</span></article>'
        self.assertEqual(b.parse_formats(page), {'film':['GOLD']})
        page = page.replace('<a href="/booking/1">3:30pm</a>', '<span class="action showtime unavailable">3:30pm</span>')
        self.assertEqual(b.parse_listed_movies(page), {'film':'Film'})
        self.assertEqual(b.parse_movies(page), {})
        self.assertEqual(b.parse_formats(page), {'film':[]})
        previous = b.merge_seen({}, {'title':'Film','dates':[],'listed_dates':['20261217']})
        self.assertEqual(previous['listed_dates'], ['20261217'])
        self.assertEqual(b.added_booking_dates(previous, {'dates':['20261217']}), ['20261217'])

    def test_same_day_showtime_notifications_stay_disabled(self):
        old = {'title':'Film','dates':['20261217'],'listed_dates':['20261217'],'sessions_by_date':{'20261217':{}},'session_baseline_v2':True}
        movie = {'title':'Film','dates':['20261217'],'sessions_by_date':{'20261217':{'gold|900':{'format':'GOLD','minutes':900,'time':'3:00pm','booking_link_present':True}}}}
        self.assertEqual(b.changes({'film':old},{'film':movie}), [])

if __name__ == '__main__':
    unittest.main()
