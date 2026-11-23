"""Serves the app and forwards /api/ to the OLC service.

The OLC container listens only on 127.0.0.1, so a tablet on the same Wi-Fi reaches the API
through this server. Standard library only.

    python3 serve.py                     # http://0.0.0.0:5173, API at http://127.0.0.1:8000
    FM_API=http://host:8000 FM_PORT=5173 python3 serve.py
"""

import json
import os
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

API = os.environ.get("FM_API", "http://127.0.0.1:8000").rstrip("/")
PORT = int(os.environ.get("FM_PORT", "5173"))
ROOT = Path(__file__).resolve().parent
FORWARD_REQUEST = ("Authorization", "Content-Type")
FORWARD_RESPONSE = ("Content-Type", "Retry-After")
MAX_BODY = 64 * 1024  # the API itself allows 16 kB; this only stops abuse of the proxy


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self.proxy()
        # only the app itself is public, not serve.py, tests or eval data
        if not (self.path == "/" or self.path.split("?")[0].startswith(("/index.html", "/js/", "/css/", "/img/"))):
            return self.send_error(404)
        return super().do_GET()

    def do_PUT(self):
        self.proxy()

    def do_POST(self):
        self.proxy()

    def do_DELETE(self):
        self.proxy()

    def proxy(self):
        if not self.path.startswith("/api/"):
            return self.send_error(405)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self.reply(413, {"error": {"code": "payload_too_large", "message": "Tělo je příliš velké."}})
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(API + self.path, data=body, method=self.command)
        for name in FORWARD_REQUEST:
            if self.headers.get(name):
                req.add_header(name, self.headers[name])
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                self.relay(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            self.relay(e.code, e.headers, e.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            # 502 = retryable for the app's outbox
            self.reply(502, {"error": {"code": "upstream_unavailable", "message": "Služba API neodpovídá."}})

    def relay(self, status, headers, data):
        self.send_response(status)
        for name in FORWARD_RESPONSE:
            if headers.get(name):
                self.send_header(name, headers[name])
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def reply(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.relay(status, {"Content-Type": "application/json"}, data)


if __name__ == "__main__":
    print(f"Floorball Mate: http://0.0.0.0:{PORT}  ->  API {API}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
