import unittest
from datetime import datetime
from unittest.mock import patch
import bot as b

class CairoClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 3, 23, 55, tzinfo=tz)

def page(date, link=''):
    return (
        f'<input value="{date}" type="hidden" name="d">'
        + link
        + '<article class="movie-compare" data-slug="film"><h2>Film</h2>'
        + '<h3>City Centre Almaza</h3><strong>GOLD</strong>'
        + '<a href="/booking/one">3:30pm</a></article>'
    )

class RolloverTests(unittest.TestCase):
    def test_default_tomorrow_is_not_assigned_to_today(self):
        default = page('20261104', '<a href="/showtimes?c=city-centre-almaza&amp;d=20261216">Wed 16 Dec</a>')
        def fetch(url):
            return page('20261216') if '&d=20261216' in url else default
        with patch.object(b, 'datetime', CairoClock), patch.object(b, 'get_page', side_effect=fetch):
            result = b.collect()
        self.assertEqual(result['film']['dates'], ['20261104', '20261216'])
        self.assertNotIn('20261103', result['film']['listed_dates'])

    def test_wrong_explicit_day_is_rejected(self):
        default = page('20261104', '<a href="/showtimes?c=city-centre-almaza&amp;d=20261216">Wed 16 Dec</a>')
        def fetch(url):
            return page('20261217') if '&d=' in url else default
        with patch.object(b, 'datetime', CairoClock), patch.object(b, 'get_page', side_effect=fetch):
            with self.assertRaisesRegex(ValueError, 'does not match'):
                b.collect()

    def test_stale_default_is_rejected(self):
        with patch.object(b, 'datetime', CairoClock), patch.object(b, 'get_page', return_value=page('20261102')):
            with self.assertRaisesRegex(ValueError, 'older'):
                b.collect()

if __name__ == '__main__':
    unittest.main()
