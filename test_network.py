import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import bot

class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.sleep=patch.object(bot.time,'sleep');self.sleep.start();self.addCleanup(self.sleep.stop)
    def test_transient_failure_retries(self):
        error=urllib.error.HTTPError('https://example.com',503,'Unavailable',{},None)
        response=MagicMock();response.__enter__.return_value.read.return_value=b'ok'
        with patch.object(bot.urllib.request,'urlopen',side_effect=[error,response]) as fetch:
            self.assertEqual(bot.get_page('https://example.com'),'ok')
            self.assertEqual(fetch.call_count,2)
    def test_retries_bounded(self):
        error=urllib.error.HTTPError('https://example.com',403,'Forbidden',{},None)
        with patch.object(bot.urllib.request,'urlopen',side_effect=error) as fetch:
            with self.assertRaises(urllib.error.HTTPError):bot.get_page('https://example.com')
            self.assertEqual(fetch.call_count,3)
    def test_not_found_no_retry(self):
        error=urllib.error.HTTPError('https://example.com',404,'Missing',{},None)
        with patch.object(bot.urllib.request,'urlopen',side_effect=error) as fetch:
            with self.assertRaises(urllib.error.HTTPError):bot.get_page('https://example.com')
            self.assertEqual(fetch.call_count,1)
