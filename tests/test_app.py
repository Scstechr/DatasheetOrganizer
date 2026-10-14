import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app

class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = app.DATA
        app.DATA = Path(self.tmp.name)
        app.init()
    def tearDown(self):
        app.DATA = self.previous
        self.tmp.cleanup()
    def test_pdf_persists_and_deduplicates(self):
        first = app.save_pdf(b'%PDF-1.4\ntest', {'title': 'LM358', 'vendor': 'TI'})
        second = app.save_pdf(b'%PDF-1.4\ntest', {'title': 'other'})
        self.assertEqual(first['id'], second['id'])
        with app.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM sheets').fetchone()[0], 1)
        self.assertTrue((app.DATA / 'pdfs' / (first['id'] + '.pdf')).exists())
    def test_reject_html_download(self):
        with self.assertRaises(ValueError): app.save_pdf(b'<html>Access denied</html>', {})
    def test_reject_local_and_non_https_urls(self):
        for url in ['file:///etc/passwd', 'http://example.com/x.pdf', 'https://127.0.0.1/x.pdf', 'https://[::1]/x.pdf']:
            with self.assertRaises(ValueError): app.public_url(url)
    def test_offline_search_fallback(self):
        with patch('app.fetch', side_effect=OSError('offline')):
            data = app.search('LM358', 'Texas Instruments')
        self.assertEqual(len(data['results']), 1)
        self.assertTrue(data['warning'])
        self.assertEqual(len(data['links']), 1)
    def test_search_filters_untrusted_domains(self):
        xml = b'<rss><channel><item><title>fake</title><link>https://ti.com.evil.example/fake.pdf</link></item><item><title>part</title><link>https://www.ti.com/part.pdf</link></item></channel></rss>'
        with patch('app.fetch', return_value=xml): data = app.search('part', 'Texas Instruments')
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['title'], 'part')

if __name__ == '__main__': unittest.main()
