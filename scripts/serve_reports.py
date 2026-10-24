#!/usr/bin/env python3
"""Static server cho reports/ — gửi Cache-Control: no-store để bản mới hiện ngay.

Dùng: scripts/serve_reports.py [port]      (mặc định 8090, bind 0.0.0.0)
Khác `python3 -m http.server`: file tĩnh không bị browser/Cloudflare cache lại,
nên regenerate report xong F5 là thấy, không cần Ctrl+Shift+R.
"""
import http.server
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8090


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory="reports", **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, *a):  # im lặng
        pass


print(f"serving reports/ on http://0.0.0.0:{PORT} (no-store)")
http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
