import unittest
from unittest.mock import patch
from bot import changes, parse_movies, booking_dates

class Tests(unittest.TestCase):
    def test_new_dates_only(self):
        old = {'film': {'title': 'Film', 'dates': ['20261103']}}
        current = {'film': {'title': 'Film', 'dates': ['20261103', '20261104']}}
        with patch('bot.get_page', return_value=''):
            events = changes(old, current)
        self.assertEqual(len(events), 1)
        event = events[0]
        if isinstance(event, dict):
            text = event['caption']
            self.assertIn(booking_dates(['20261104']), text)
            self.assertNotIn(booking_dates(['20261103']), text)
            self.assertIn('city-centre-almaza', event['url'])
        else:
            self.assertIn('04/11/2026', event)
            self.assertNotIn('03/11/2026', event)
        self.assertEqual(changes(current, current), [])

    def test_only_bookable_almaza(self):
        page = '<article class="movie-compare" data-slug="film"><h2>Film</h2><h3>City Centre Almaza</h3><a href="/booking/1">Book</a></article>'
        self.assertEqual(parse_movies(page), {'film': 'Film'})
        self.assertEqual(parse_movies(page.replace('/booking/1', '/movies/film')), {})

if __name__ == '__main__':
    unittest.main()
