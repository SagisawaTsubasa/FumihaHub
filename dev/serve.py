#!/usr/bin/env python3
"""Offline dev server for the Fumiha Hub shell.

Mirrors HA's static-path mounts so the REAL shell, kit and page modules load
unchanged (same approach as the Stockroom / WHA dev harnesses — stdlib only,
no build, no HMR; refresh to pick up edits):

    /                -> dev/index.html  (harness with mockHass)
    /fumiha_hub/*    -> custom_components/fumiha_hub/static/*
    /devstub/*       -> dev/stub-pages/*

REST APIs are intercepted client-side by mockHass in index.html, so the
server only serves files. Usage: python dev/serve.py [port] (default 8770).
"""

from __future__ import annotations

import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEV_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEV_DIR.parent
STATIC_DIR = REPO_ROOT / "custom_components" / "fumiha_hub" / "static"
STUB_DIR = DEV_DIR / "stub-pages"

DEFAULT_PORT = 8770


class HubDevHandler(SimpleHTTPRequestHandler):
    def _safe(self, root: Path, rel: str) -> str:
        """Resolve rel under root; anything escaping the root 404s (FXH-F-015:
        a bare client can send `..` segments the browser would normalize)."""
        resolved = (root / rel).resolve()
        if resolved != root and root not in resolved.parents:
            return str((DEV_DIR / "__escaped__").resolve())
        return str(resolved)

    def list_directory(self, path: str) -> None:
        # stdlib would serve a 200 HTML listing for directory URLs; HA's
        # static mount never does. Send a clean 404 instead (FXH-F-024);
        # returning None tells do_GET there is no body to copy.
        self.send_error(404, "Directory listing not supported")
        return None

    def translate_path(self, path: str) -> str:
        # Same order as stdlib: strip query/fragment, then percent-decode —
        # browsers encode non-ASCII asset names and the mirror promise
        # requires decoding them like HA's static handler would (FXH-F-021).
        path = path.split("?", 1)[0].split("#", 1)[0]
        path = urllib.parse.unquote(path)
        # unquote can produce a NUL byte (%00): Path.resolve() raises
        # ValueError on embedded nulls, which would surface as a traceback +
        # dropped connection instead of a clean 404 (FXH-F-022).
        if "\x00" in path:
            return str((DEV_DIR / "__escaped__").resolve())
        if path.startswith("/fumiha_hub/"):
            return self._safe(STATIC_DIR, path[len("/fumiha_hub/"):])
        if path.startswith("/devstub/"):
            return self._safe(STUB_DIR, path[len("/devstub/"):])
        if path in ("", "/"):
            return str(DEV_DIR / "index.html")
        return self._safe(DEV_DIR, path.lstrip("/"))

    def end_headers(self) -> None:
        # Dev assets must never be cached by the browser (same intent as the
        # production `cache_headers=False`).
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        sys.stderr.write("[dev] %s\n" % (format % args))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server = ThreadingHTTPServer(("127.0.0.1", port), HubDevHandler)
    print(f"[dev] Fumiha Hub harness on http://127.0.0.1:{port}/  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
