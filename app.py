"""Local, dependency-free datasheet organizer."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import threading
import urllib.parse
import urllib.request
import webbrowser
from contextlib import contextmanager
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('DATASHEET_HOME', str(Path.home() / '.datasheet-organizer')))
VENDORS = {'ti.com': 'Texas Instruments', 'analog.com': 'Analog Devices', 'st.com': 'STMicroelectronics', 'microchip.com': 'Microchip', 'nxp.com': 'NXP', 'infineon.com': 'Infineon', 'onsemi.com': 'onsemi', 'renesas.com': 'Renesas'}
CATALOG = [
    {'title': 'LM358 · Dual operational amplifier', 'vendor': 'Texas Instruments', 'url': 'https://www.ti.com/lit/ds/symlink/lm358.pdf'},
    {'title': 'AD620 · Instrumentation amplifier', 'vendor': 'Analog Devices', 'url': 'https://www.analog.com/media/en/technical-documentation/data-sheets/ad620.pdf'},
    {'title': 'STM32F103C8 · Arm Cortex-M3 microcontroller', 'vendor': 'STMicroelectronics', 'url': 'https://www.st.com/resource/en/datasheet/stm32f103c8.pdf'},
]
MAX_FILE = 40 * 1024 * 1024

@contextmanager
def db():
    con = sqlite3.connect(DATA / 'library.sqlite')
    con.row_factory = sqlite3.Row
    try:
        with con:
            yield con
    finally:
        con.close()

def init():
    (DATA / 'pdfs').mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS sheets (id TEXT PRIMARY KEY, title TEXT NOT NULL, vendor TEXT, url TEXT, tags TEXT DEFAULT "", notes TEXT DEFAULT "", favorite INTEGER DEFAULT 0, size INTEGER, created TEXT DEFAULT CURRENT_TIMESTAMP)')

def public_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('Use a public HTTPS PDF URL.')
    for addr in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(addr[4][0]).is_global:
            raise ValueError('Private network URLs are not allowed.')
    return url

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def fetch(url, limit=MAX_FILE):
    public_url(url)
    opener = urllib.request.build_opener(SafeRedirect())
    with opener.open(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 DatasheetOrganizer/1.0'}), timeout=20) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('File exceeds the 40 MB limit.')
    return data

def save_pdf(data, meta):
    if not data.startswith(b'%PDF-'):
        raise ValueError('The response is not a PDF. Open the vendor website or import the PDF manually.')
    ident = hashlib.sha256(data).hexdigest()[:24]
    (DATA / 'pdfs' / (ident + '.pdf')).write_bytes(data)
    with db() as con:
        con.execute('INSERT OR IGNORE INTO sheets (id,title,vendor,url,tags,size) VALUES (?,?,?,?,?,?)', (ident, str(meta.get('title') or 'Untitled datasheet')[:200], str(meta.get('vendor', ''))[:100], str(meta.get('url', ''))[:2000], str(meta.get('tags', ''))[:1000], len(data)))
        return dict(con.execute('SELECT * FROM sheets WHERE id=?', (ident,)).fetchone())

def search(query, vendor):
    selected = [domain for domain, name in VENDORS.items() if not vendor or name == vendor]
    if not selected:
        raise ValueError('Unknown vendor.')
    results = [dict(x, source='Reference catalog') for x in CATALOG if (not vendor or x['vendor'] == vendor) and query.lower() in x['title'].lower()]
    # Bing RSS is a public search endpoint; failures are surfaced alongside vendor search links.
    expression = query + ' datasheet filetype:pdf (' + ' OR '.join('site:' + d for d in selected) + ')'
    warning = ''
    try:
        class RSSParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.items, self.current, self.field = [], None, None
            def handle_starttag(self, tag, attrs):
                if tag == 'item': self.current = {}
                elif self.current is not None and tag in ('title', 'link'): self.field = tag
            def handle_data(self, data):
                if self.current is not None and self.field:
                    self.current[self.field] = self.current.get(self.field, '') + data
            def handle_endtag(self, tag):
                if tag == 'item' and self.current is not None:
                    self.items.append(self.current)
                    self.current = None
                self.field = None
        parser = RSSParser()
        parser.feed(fetch('https://www.bing.com/search?format=rss&q=' + urllib.parse.quote(expression), 2 * 1024 * 1024).decode('utf-8', errors='replace'))
        for item in parser.items:
            url = item.get('link', '').strip()
            host = urllib.parse.urlsplit(url).hostname or ''
            domain = next((d for d in selected if host == d or host.endswith('.' + d)), None)
            if domain and re.search(r'\.pdf(?:\?|$)', url, re.I) and not any(x['url'] == url for x in results):
                results.append({'title': item.get('title') or query, 'vendor': VENDORS[domain], 'url': url, 'source': 'Web search'})
    except Exception:
        warning = 'Online search is unavailable. Use the vendor search links below, or paste a PDF URL to download.'
    links = [{'vendor': VENDORS[d], 'url': 'https://www.google.com/search?q=' + urllib.parse.quote('site:' + d + ' ' + query + ' datasheet pdf')} for d in selected]
    return {'results': results, 'warning': warning, 'links': links}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass
    def output(self, data, status=200, mime='application/json'):
        body = json.dumps(data).encode() if mime == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        args = urllib.parse.parse_qs(path.query)
        try:
            if path.path == '/api/library':
                with db() as con:
                    self.output([dict(x) for x in con.execute('SELECT * FROM sheets ORDER BY created DESC')])
            elif path.path == '/api/vendors':
                self.output(list(VENDORS.values()))
            elif path.path == '/api/search':
                query = args.get('q', [''])[0].strip()[:200]
                if not query: raise ValueError('Enter a part number or keyword.')
                self.output(search(query, args.get('vendor', [''])[0]))
            elif re.fullmatch(r'/pdf/[a-f0-9]{24}', path.path):
                self.output((DATA / 'pdfs' / (path.path.split('/')[-1] + '.pdf')).read_bytes(), mime='application/pdf')
            elif path.path in ('/', '/app.js', '/style.css'):
                name = 'index.html' if path.path == '/' else path.path[1:]
                mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
                self.output((ROOT / 'static' / name).read_bytes(), mime=mime)
            else: self.output({'error': 'Not found'}, 404)
        except FileNotFoundError: self.output({'error': 'Not found'}, 404)
        except Exception as exc: self.output({'error': str(exc)}, 400)
    def do_POST(self):
        # Reject cross-origin writes to this local service.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            return self.output({'error': 'Cross-origin requests are blocked'}, 403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_FILE: raise ValueError('Request is empty or exceeds 40 MB.')
            body = self.rfile.read(length)
            if self.path == '/api/import':
                title = urllib.parse.unquote(self.headers.get('X-Filename', 'Imported datasheet'))
                self.output(save_pdf(body, {'title': title.removesuffix('.pdf'), 'vendor': 'Local import'}))
                return
            meta = json.loads(body)
            if self.path == '/api/download': self.output(save_pdf(fetch(meta['url']), meta))
            elif self.path == '/api/update':
                with db() as con:
                    cur = con.execute('UPDATE sheets SET title=?,tags=?,notes=?,favorite=? WHERE id=?', (str(meta['title'])[:200], str(meta.get('tags', ''))[:1000], str(meta.get('notes', ''))[:10000], int(bool(meta.get('favorite'))), meta['id']))
                    if not cur.rowcount: raise ValueError('Datasheet not found.')
                self.output({'ok': True})
            elif self.path == '/api/delete':
                if not re.fullmatch('[a-f0-9]{24}', str(meta['id'])): raise ValueError('Invalid ID.')
                with db() as con: con.execute('DELETE FROM sheets WHERE id=?', (meta['id'],))
                (DATA / 'pdfs' / (meta['id'] + '.pdf')).unlink(missing_ok=True)
                self.output({'ok': True})
            else: self.output({'error': 'Not found'}, 404)
        except Exception as exc: self.output({'error': str(exc)}, 400)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    init()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    address = f'http://127.0.0.1:{server.server_port}'
    print(f'Datasheet Organizer: {address}\nLibrary: {DATA}', flush=True)
    if not args.no_browser: threading.Timer(0.5, lambda: webbrowser.open(address)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

if __name__ == '__main__': main()
