#!/usr/bin/env python3
"""「층위(層位)」 보호 서버 — web/ 정적 서빙 + 봇 차단 + 보안 헤더.

- 검색엔진·크롤러·AI봇·스크립트 UA 는 403
- X-Robots-Tag: noindex — 헤더 수준 색인 금지
- 실행: python3 serve.py [포트]   (기본 8768)

링크 카드 미리보기 봇(linkedinbot·slackbot·kakaotalk-scrap 등)은 차단 토큰을
달고 오지 않아 그대로 통과한다. 허용 목록을 따로 두지 않는 이유는, 허용이
차단을 덮는 순간 "GPTBot ... LinkedInBot" 같은 결합 UA 로 우회할 수 있어서다.
"""

import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parent / "web"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8768

BLOCK = ("googlebot", "bingbot", "yandexbot", "baiduspider", "duckduckbot",
         "semrush", "ahrefs", "mj12bot", "petalbot", "bytespider", "gptbot",
         "ccbot", "claudebot", "claude-web", "amazonbot", "applebot",
         "crawler", "spider", "scrapy", "curl/", "wget/", "python-requests",
         "python-urllib", "go-http-client", "okhttp", "httpx", "aiohttp")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEB), **kw)

    def end_headers(self):
        self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _blocked(self) -> bool:
        ua = (self.headers.get("User-Agent") or "").lower()
        if not ua:
            return True
        return any(b in ua for b in BLOCK)

    def do_GET(self):
        if self._blocked():
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"403")
            return
        super().do_GET()

    do_HEAD = do_GET

    def log_message(self, fmt, *args):  # 소음 축소 — 4xx·5xx 만 남긴다
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    if not WEB.is_dir():
        sys.exit("web/ 이 없다 — make build 를 먼저 돌려라: %s" % WEB)
    print("층위 서버: http://localhost:%d ← %s" % (PORT, WEB))
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
