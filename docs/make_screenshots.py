#!/usr/bin/env python3
"""Regenerates the images in docs/ with fake values only. macOS, run from the repo root:

    python3 docs/make_screenshots.py

popup-<lang>.png     the real dialog, prefilled with a fake value and captured with `screencapture -l`
terminal-<lang>.svg  real CLI output: a fake `ssh` runs the remote script locally and a fake
                     Google token endpoint answers the OAuth code exchange
"""

import html
import http.server
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
CLI = os.path.join(ROOT, "secret-drop")
FAKE = "sk_test_FAKE_0000000000000000"
NOTES = {"en": "Stripe Dashboard → Developers → API keys", "tr": "Stripe Paneli → Geliştiriciler → API anahtarları"}
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CLIENT_ID = "1234-fake.apps.googleusercontent.com"

loader = importlib.machinery.SourceFileLoader("secret_drop", CLI)
sd = sys.modules["secret_drop"] = importlib.util.module_from_spec(importlib.util.spec_from_loader("secret_drop", loader))
loader.exec_module(sd)

WINDOW_ID = """
import CoreGraphics
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as! [[String: Any]]
for w in list where (w[kCGWindowOwnerName as String] as? String) == "System Events" {
  print(w[kCGWindowNumber as String]!); break
}
"""


def strip_metadata(path: str) -> None:
    """Drops EXIF/XMP/text chunks that screencapture adds; keeps only what draws the image."""
    with open(path, "rb") as f:
        data = f.read()
    out, pos = [data[:8]], 8
    while pos < len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        chunk = data[pos:pos + 12 + length]
        if chunk[4:8] not in (b"eXIf", b"iTXt", b"tEXt", b"zTXt"):
            out.append(chunk)
        pos += 12 + length
    with open(path, "wb") as f:
        f.write(b"".join(out))


def popup(lang: str) -> None:
    m = sd.MESSAGES[lang]
    script = sd.OSASCRIPT.replace('default answer ""', "default answer (item 6 of argv)")
    text = m["paste"].format(name="STRIPE_SECRET_KEY") + "\n\n" + NOTES[lang]
    proc = subprocess.Popen(["osascript", "-", text, m["title"], m["cancel"], m["save"], "60", FAKE],
                            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
    proc.stdin.write(script)
    proc.stdin.close()
    time.sleep(4)
    window = subprocess.run(["swift", "-"], input=WINDOW_ID, capture_output=True, text=True).stdout.strip()
    path = os.path.join(DOCS, f"popup-{lang}.png")
    subprocess.run(["screencapture", "-x", f"-l{window}", path], check=True)
    strip_metadata(path)
    proc.terminate()
    subprocess.run(["pkill", "-f", "osascript - "], check=False)


class FakeGoogle(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers["content-length"]))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"refresh_token": "1//fake-refresh", "scope": SCOPE}).encode())

    def log_message(self, *_):
        pass


def transcript(lang: str) -> list[tuple[str, str]]:
    """Runs the real CLI and returns (kind, line) pairs; kind is 'cmd' or 'out'."""
    tmp = tempfile.mkdtemp()
    bin_dir = os.path.join(tmp, "bin")
    os.mkdir(bin_dir)
    with open(os.path.join(bin_dir, "ssh"), "w") as f:  # runs the remote script locally
        f.write('#!/bin/sh\nwhile [ "$1" = -o ]; do shift 2; done\nshift\nexec sh -c "$*"\n')
    os.chmod(os.path.join(bin_dir, "ssh"), 0o755)
    config = os.path.join(tmp, "config")
    with open(config, "w") as f:
        f.write(textwrap.dedent(f"""\
            [target.prod]
            target = ssh:deploy@app.example.com:{tmp}/app.env
            then = true
            """))
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "SECRET_DROP_CONFIG": config,
           "SECRET_DROP_LANG": lang, "SECRET_DROP_PROMPTER": f"printf %s {FAKE}"}

    server = http.server.HTTPServer(("127.0.0.1", 0), FakeGoogle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    launcher = (
        "import importlib.machinery, importlib.util, sys; "
        f"l = importlib.machinery.SourceFileLoader('m', {CLI!r}); "
        "m = sys.modules['m'] = importlib.util.module_from_spec(importlib.util.spec_from_loader('m', l)); "
        f"l.exec_module(m); m.GOOGLE_TOKEN_URL = 'http://127.0.0.1:{server.server_address[1]}/token'; "
        "sys.argv[0] = 'secret-drop'; sys.exit(m.main(sys.argv[1:]))"
    )

    lines: list[tuple[str, str]] = []

    def run(display: list[str], argv: list[str], consent: bool = False) -> None:
        lines.append(("cmd", " ".join(display)))
        proc = subprocess.Popen([sys.executable, "-c", launcher, *argv], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in proc.stdout:
            line = line.rstrip("\n")
            if consent and line.startswith("AUTH_URL "):
                query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(line[9:]).query))
                callback = query["redirect_uri"] + "/?" + urllib.parse.urlencode({"code": "x", "state": query["state"]})
                threading.Thread(target=lambda: urllib.request.urlopen(callback).read(), daemon=True).start()
                line = line[:96] + "…"
            lines.append(("out", line))
        proc.wait()

    run(["secret-drop", "ask", "STRIPE_SECRET_KEY", "@prod", f'"{NOTES[lang]}"'],
        ["ask", "STRIPE_SECRET_KEY", "@prod", NOTES[lang]])
    run(["secret-drop", "google-oauth", "GMAIL", CLIENT_ID, f'"{SCOPE}"', "@prod", "--no-open"],
        ["google-oauth", "GMAIL", CLIENT_ID, SCOPE, "@prod", "--no-open"], consent=True)
    server.shutdown()
    return lines


def svg(lines: list[tuple[str, str]], path: str) -> None:
    char_w, line_h, pad, top = 8.4, 22, 24, 52
    width = int(max(len(t) + 2 for _, t in lines) * char_w + pad * 2)
    height = top + len(lines) * line_h + pad
    rows = []
    for i, (kind, text) in enumerate(lines):
        y = top + (i + 1) * line_h - 6
        body = html.escape(text)
        if kind == "cmd":
            rows.append(f'<text x="{pad}" y="{y}"><tspan fill="#7ee787">$ </tspan>{body}</text>')
        else:
            color = "#9da7b3" if text.startswith(("AUTH_URL", "Open", "Bu adresi")) else "#e6edf3"
            rows.append(f'<text x="{pad}" y="{y}" fill="{color}">{body}</text>')
    content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" rx="12" fill="#0d1117"/>
<circle cx="22" cy="20" r="6" fill="#ff5f57"/><circle cx="42" cy="20" r="6" fill="#febc2e"/><circle cx="62" cy="20" r="6" fill="#28c840"/>
<g font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace" font-size="14" fill="#e6edf3" xml:space="preserve">
{chr(10).join(rows)}
</g>
</svg>
"""
    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    for lang in ("en", "tr"):
        svg(transcript(lang), os.path.join(DOCS, f"terminal-{lang}.svg"))
        if sys.platform == "darwin" and "--no-popup" not in sys.argv:
            popup(lang)
    print("docs/ updated")
