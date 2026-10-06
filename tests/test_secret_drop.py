"""Tests run without a GUI: SECRET_DROP_PROMPTER stands in for the dialog and a fake `ssh` runs
the remote script locally. Run with: python3 -m unittest discover -s tests"""

import base64
import hashlib
import http.server
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(ROOT, "secret-drop")
VALUE = "fake-value-0123456789"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.config = os.path.join(self.dir, "config")
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": self.dir,
            "SECRET_DROP_CONFIG": self.config,
            "SECRET_DROP_LANG": "en",
            "SECRET_DROP_PROMPTER": 'printf %s "$FAKE_VALUE"',
            "FAKE_VALUE": VALUE,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, **env):
        result = subprocess.run([sys.executable, CLI, *args], env={**self.env, **env},
                                capture_output=True, text=True, timeout=60)
        self.assertNotIn(VALUE, result.stdout + result.stderr, "value leaked to output")
        return result

    def path(self, name):
        return os.path.join(self.dir, name)

    def read(self, name):
        with open(self.path(name)) as f:
            return f.read()


class FileTarget(Base):
    def test_writes_with_0600_and_reports_length(self):
        r = self.run_cli("ask", "API_KEY", f"file:{self.path('env')}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"(length {len(VALUE)})", r.stdout)
        self.assertEqual(self.read("env"), f"API_KEY={VALUE}\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.path("env")).st_mode), 0o600)

    def test_replaces_existing_line_and_keeps_others(self):
        with open(self.path("env"), "w") as f:
            f.write("A=1\nAPI_KEY=old\nB=2\n")
        self.run_cli("ask", "API_KEY", f"file:{self.path('env')}")
        self.assertEqual(self.read("env"), f"A=1\nB=2\nAPI_KEY={VALUE}\n")

    def test_tilde_is_expanded(self):
        r = self.run_cli("ask", "API_KEY", "file:~/env")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("API_KEY=", self.read("env"))

    def test_missing_directory_fails_before_prompting(self):
        r = self.run_cli("ask", "API_KEY", f"file:{self.path('nope/env')}",
                         SECRET_DROP_PROMPTER=f"touch {self.path('prompted')}")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(self.path("prompted")))


class Validation(Base):
    def test_rejects_bad_names(self):
        for name in ("api_key", "1KEY", "KEY;rm", "KEY=X", ""):
            r = self.run_cli("ask", name, f"file:{self.path('env')}")
            self.assertEqual(r.returncode, 2, name)
        self.assertFalse(os.path.exists(self.path("env")))

    def test_rejects_unknown_target(self):
        for target in ("nope", "ftp:x", "ssh:hostonly", "file:"):
            self.assertEqual(self.run_cli("ask", "KEY", target).returncode, 2, target)

    def test_empty_value_means_cancel(self):
        r = self.run_cli("ask", "KEY", f"file:{self.path('env')}", FAKE_VALUE="  ")
        self.assertEqual(r.returncode, 1)
        self.assertIn("cancelled", r.stderr)
        self.assertFalse(os.path.exists(self.path("env")))

    def test_line_break_is_rejected(self):
        r = self.run_cli("ask", "KEY", f"file:{self.path('env')}",
                         SECRET_DROP_PROMPTER="printf 'abc\\nEVIL=1'")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(self.path("env")))

    def test_surrounding_whitespace_is_trimmed(self):
        self.run_cli("ask", "KEY", f"file:{self.path('env')}", FAKE_VALUE=f"  {VALUE}\n")
        self.assertEqual(self.read("env"), f"KEY={VALUE}\n")

    def test_turkish_messages(self):
        r = self.run_cli("ask", "KEY", f"file:{self.path('env')}", SECRET_DROP_LANG="tr")
        self.assertIn("yazıldı", r.stdout)


class ExecAndThen(Base):
    def test_exec_gets_value_on_stdin_and_name_in_env(self):
        out = self.path("out")
        r = self.run_cli("ask", "KEY", f'exec:{{ printf %s "$SECRET_DROP_NAME:"; cat; }} > {out}; echo "$FAKE_VALUE"')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read("out"), f"KEY:{VALUE}")

    def test_exec_failure_is_reported(self):
        r = self.run_cli("ask", "KEY", "exec:exit 3")
        self.assertEqual(r.returncode, 1)
        self.assertIn("exit 3", r.stderr)

    def test_then_runs_after_write_without_the_value(self):
        log = self.path("then")
        r = self.run_cli("ask", "KEY", f"file:{self.path('env')}",
                         "--then", f'env > {log}; echo "$SECRET_DROP_NAMES $SECRET_DROP_TARGET" >> {log}')
        self.assertEqual(r.returncode, 0, r.stderr)
        log_text = self.read("then")
        self.assertIn(f"KEY file:{self.path('env')}", log_text)
        self.assertNotIn(VALUE, log_text.replace(f"FAKE_VALUE={VALUE}", ""))

    def test_then_failure_is_reported(self):
        r = self.run_cli("ask", "KEY", f"file:{self.path('env')}", "--then", "exit 4")
        self.assertEqual(r.returncode, 1)
        self.assertIn("exit 4", r.stderr)


class Aliases(Base):
    def test_alias_with_then(self):
        with open(self.config, "w") as f:
            f.write(textwrap.dedent(f"""\
                [target.app]
                target = file:{self.path('env')}
                then = touch {self.path('restarted')}
                """))
        for spec in ("@app", "app"):
            r = self.run_cli("ask", "KEY", spec)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("KEY → @app written", r.stdout)
        self.assertTrue(os.path.exists(self.path("restarted")))
        self.assertIn("@app", self.run_cli("targets").stdout)


class SshTarget(Base):
    def setUp(self):
        super().setUp()
        bin_dir = self.path("bin")
        os.mkdir(bin_dir)
        with open(os.path.join(bin_dir, "ssh"), "w") as f:
            f.write(textwrap.dedent(f"""\
                #!/bin/sh
                printf '%s\\n' "$*" >> {self.path('ssh-argv')}
                while [ "$1" = -o ]; do shift 2; done
                shift
                exec sh -c "$*"
                """))
        os.chmod(os.path.join(bin_dir, "ssh"), 0o755)
        self.env["PATH"] = f"{bin_dir}:{self.env['PATH']}"

    def test_value_travels_over_stdin_not_argv(self):
        remote = self.path("remote env")  # a space, to exercise quoting
        with open(remote, "w") as f:
            f.write("OTHER=1\nKEY=old\n")
        r = self.run_cli("ask", "KEY", f"ssh:myhost:{remote}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read("remote env"), f"OTHER=1\nKEY={VALUE}\n")
        self.assertEqual(stat.S_IMODE(os.stat(remote).st_mode), 0o600)
        self.assertNotIn(VALUE, self.read("ssh-argv"))
        self.assertEqual(os.listdir(self.dir).count("remote env"), 1)  # no temp file left behind

    def test_remote_home_path(self):
        r = self.run_cli("ask", "KEY", "ssh:myhost:~/app.env")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read("app.env"), f"KEY={VALUE}\n")

    def test_unreachable_host_fails_before_prompting(self):
        bad = os.path.join(self.path("bin"), "ssh")
        with open(bad, "w") as f:
            f.write("#!/bin/sh\nexit 255\n")
        r = self.run_cli("ask", "KEY", "ssh:myhost:/x", SECRET_DROP_PROMPTER=f"touch {self.path('prompted')}")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(os.path.exists(self.path("prompted")))


@unittest.skipUnless(sys.platform == "darwin" and os.environ.get("SECRET_DROP_TEST_KEYCHAIN") == "1",
                     "set SECRET_DROP_TEST_KEYCHAIN=1 on macOS to write to the login keychain")
class KeychainTarget(Base):
    SERVICE = "secret-drop test service"

    def tearDown(self):
        subprocess.run(["security", "delete-generic-password", "-s", self.SERVICE, "-a", "KEY"], capture_output=True)
        super().tearDown()

    def test_round_trip(self):
        self.env["PATH"] = os.environ["PATH"]
        self.env["HOME"] = os.environ["HOME"]  # the login keychain lives under the real home
        for value in (VALUE, VALUE + "-updated"):
            r = self.run_cli("ask", "KEY", f"keychain:{self.SERVICE}", FAKE_VALUE=value)
            self.assertEqual(r.returncode, 0, r.stderr)
            stored = subprocess.run(["security", "find-generic-password", "-s", self.SERVICE, "-a", "KEY", "-w"],
                                    capture_output=True, text=True).stdout.strip()
            self.assertEqual(stored, value)


class FakeGoogle(http.server.BaseHTTPRequestHandler):
    """Token endpoint that checks the PKCE verifier against the challenge it was given."""

    challenge = ""

    def do_POST(self):  # noqa: N802
        form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["content-length"])).decode())
        verifier = form["code_verifier"][0]
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        ok = digest == FakeGoogle.challenge and form["code"] == ["fake-code"] and form["client_secret"] == [VALUE]
        body = {"refresh_token": "fake-refresh-token", "scope": "openid"} if ok else {"error": "invalid_grant"}
        self.send_response(200 if ok else 400)
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, *_):
        pass


class GoogleOAuth(Base):
    def run_flow(self, *extra, deny=False):
        server = http.server.HTTPServer(("127.0.0.1", 0), FakeGoogle)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        launcher = (
            "import importlib.machinery, importlib.util, sys; "
            f"loader = importlib.machinery.SourceFileLoader('sd', {CLI!r}); "
            "m = sys.modules['sd'] = importlib.util.module_from_spec(importlib.util.spec_from_loader('sd', loader)); "
            "loader.exec_module(m); "
            f"m.GOOGLE_TOKEN_URL = 'http://127.0.0.1:{server.server_address[1]}/token'; "
            "sys.exit(m.main(sys.argv[1:]))"
        )
        args = [sys.executable, "-c", launcher, "google-oauth", "GMAIL", "fake-id.apps.googleusercontent.com",
                "openid", f"file:{self.path('env')}", "--no-open", *extra]
        proc = subprocess.Popen(args, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in proc.stdout:
            if line.startswith("AUTH_URL "):
                auth = urllib.parse.urlparse(line.split(" ", 1)[1].strip())
                break
        query = {k: v[0] for k, v in urllib.parse.parse_qs(auth.query).items()}
        FakeGoogle.challenge = query["code_challenge"]
        self.assertEqual(query["code_challenge_method"], "S256")
        # A stray request with the wrong state must be ignored.
        with self.assertRaises(urllib.error.HTTPError) as stray:
            urllib.request.urlopen(query["redirect_uri"] + "/?code=evil&state=wrong", timeout=5)
        stray.exception.close()
        reply = {"error": "access_denied"} if deny else {"code": "fake-code"}
        urllib.request.urlopen(query["redirect_uri"] + "/?" + urllib.parse.urlencode({**reply, "state": query["state"]}),
                               timeout=5).read()
        out, err = proc.communicate(timeout=30)
        self.assertNotIn(VALUE, out + err)
        return proc.returncode, out, err

    def test_full_flow_writes_three_values(self):
        code, out, err = self.run_flow()
        self.assertEqual(code, 0, err)
        self.assertIn("GMAIL: client + refresh token", out)
        self.assertEqual(self.read("env"), "GMAIL_CLIENT_ID=fake-id.apps.googleusercontent.com\n"
                                           f"GMAIL_CLIENT_SECRET={VALUE}\nGMAIL_REFRESH_TOKEN=fake-refresh-token\n")

    def test_reuse_secret_reads_from_target(self):
        with open(self.path("env"), "w") as f:
            f.write(f"GMAIL_CLIENT_SECRET={VALUE}\n")
        self.env["SECRET_DROP_PROMPTER"] = "exit 1"  # proves the dialog is not used
        code, _, err = self.run_flow("--reuse-secret")
        self.assertEqual(code, 0, err)
        self.assertIn("GMAIL_REFRESH_TOKEN=fake-refresh-token", self.read("env"))

    def test_denied_consent_writes_nothing(self):
        code, _, err = self.run_flow(deny=True)
        self.assertEqual(code, 1)
        self.assertIn("access_denied", err)
        self.assertFalse(os.path.exists(self.path("env")))


if __name__ == "__main__":
    unittest.main()
