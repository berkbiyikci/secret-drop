# secret-drop

**Hand secrets to your tools without pasting them into an AI chat.**

[Türkçe](README.tr.md)

![Demo: the agent asks for a key, a native dialog opens, the key is written to its target and never shows up in the chat](docs/demo-en.gif)

## Why

Coding agents like Claude Code and Codex often need an API key, an OAuth client secret or a refresh
token to finish a task. The usual flow goes like this: the agent says "run this and paste the key",
and the key ends up pasted into the chat. From that point it lives in the transcript, in the agent's
context and in whatever logs the provider or your tooling keeps.

secret-drop moves the secret off the chat and onto your screen. The agent runs a command, a native
password dialog opens on your machine, you paste the key there, and the value is written straight to
where it belongs: an env file, a server over ssh, the macOS Keychain or a command of your own. The
agent only gets told the value's **length**, which is enough to confirm it worked.

<img src="docs/popup-en.png" width="520" alt="The secret-drop dialog: a padlock, 'Paste the value for STRIPE_SECRET_KEY', a hint line and a hidden field">

## Install

No package manager and no `curl | sh`. It is one Python file with no dependencies beyond the standard
library (Python 3.9+, which ships with macOS).

```bash
git clone https://github.com/berkbiyikci/secret-drop.git ~/tools/secret-drop
echo 'export PATH="$HOME/tools/secret-drop:$PATH"' >> ~/.zshrc
exec zsh
secret-drop --version
```

The first time the dialog opens, macOS asks whether your terminal (or the app running your agent) may
control **System Events**. Allow it; that is how the dialog comes to the front.

## Usage

### `ask`: one secret, one target

```bash
secret-drop ask NAME TARGET ["hint shown in the dialog"] [--then "command"]
```

`NAME` must look like an environment variable (`^[A-Z][A-Z0-9_]*$`). The dialog closes on its own
after 10 minutes. Cancelling, timing out or submitting an empty field writes nothing.

| Target | What happens |
|---|---|
| `file:<path>` | Sets `NAME=value` in a local env file. Other lines are kept, the write is atomic and the file ends up with mode `600`. |
| `ssh:<host>:<path>` | Does the same on a remote host. The value travels over ssh's **stdin**, never on the command line. `<host>` can be anything `ssh` accepts, including aliases from `~/.ssh/config`. |
| `keychain:<service>` | Stores a generic password in the macOS login keychain (service = `<service>`, account = `NAME`). The value goes to `security -i` over stdin. |
| `exec:<command>` | Runs a shell command with the value on **stdin** and the name in `$SECRET_DROP_NAME`. The command's stdout is discarded, so it cannot echo the value back to the agent. |
| `@<name>` | A target defined in the config file (see below). |

```bash
# local .env
secret-drop ask OPENAI_API_KEY file:.env "platform.openai.com → API keys"

# env file on a server, then restart the service
secret-drop ask STRIPE_SECRET_KEY ssh:deploy@app.example.com:/srv/app/.env \
  "Stripe Dashboard → Developers → API keys" \
  --then "ssh deploy@app.example.com sudo systemctl restart app"

# macOS Keychain
secret-drop ask GITHUB_TOKEN keychain:my-scripts

# anything that reads stdin, e.g. a GitHub Actions secret
secret-drop ask NPM_TOKEN 'exec:gh secret set "$SECRET_DROP_NAME" --repo me/my-lib'
```

On success, `ask` prints one line:

```
STRIPE_SECRET_KEY → @prod written (length 107)
```

`--then` runs after a successful write. It never sees the value; it gets `$SECRET_DROP_NAMES` and
`$SECRET_DROP_TARGET` in its environment.

### `google-oauth`: a refresh token without copy-paste

```bash
secret-drop google-oauth PREFIX CLIENT_ID "SCOPES" TARGET [--no-open] [--reuse-secret] [--then "command"]
```

This runs the whole Google OAuth consent flow for an **OAuth client of type "Desktop app"**:

1. Asks for the client secret in the dialog (or, with `--reuse-secret`, reads `PREFIX_CLIENT_SECRET`
   back from the target, which is useful when you re-authorize).
2. Starts a one-shot listener on `127.0.0.1` on a random port, with a `state` check and PKCE (S256).
3. Opens the consent screen in your browser. With `--no-open` it prints the URL as `AUTH_URL <url>`
   instead, so you can open it in a specific Chrome profile.
4. Exchanges the code and writes `PREFIX_CLIENT_ID`, `PREFIX_CLIENT_SECRET` and
   `PREFIX_REFRESH_TOKEN` to the target.

```bash
secret-drop google-oauth GMAIL 1234-abc.apps.googleusercontent.com \
  "https://www.googleapis.com/auth/gmail.readonly" @prod --no-open
```

<img src="docs/terminal-en.svg" alt="Terminal output of secret-drop ask and google-oauth, showing only names, targets and lengths">

### Config file and named targets

`~/.config/secret-drop/config` (or `$XDG_CONFIG_HOME/secret-drop/config`, or `$SECRET_DROP_CONFIG`):

```ini
[settings]
# en or tr; defaults to your locale
lang = en
# seconds before the dialog gives up
timeout = 600

[target.prod]
target = ssh:deploy@app.example.com:/srv/app/.env
then = ssh deploy@app.example.com sudo systemctl restart app

[target.local]
target = file:~/projects/app/.env
```

Then `secret-drop ask STRIPE_SECRET_KEY @prod` writes to the server and restarts the service, and
`secret-drop targets` lists what is configured, so an agent can discover where things go.

| Environment variable | Meaning |
|---|---|
| `SECRET_DROP_CONFIG` | Path to the config file. |
| `SECRET_DROP_LANG` | `en` or `tr`. Overrides the config and your locale. |
| `SECRET_DROP_TIMEOUT` | Dialog timeout in seconds. |
| `SECRET_DROP_PROMPTER` | A shell command that prints the secret on stdout, used instead of the dialog. It receives `$SECRET_DROP_NAME` and `$SECRET_DROP_PROMPT`. The tests use it; you could also point it at a password manager CLI. |

## Tell your agent

Paste this into `CLAUDE.md`, `AGENTS.md` or your agent's system prompt:

```markdown
## Secrets
- Never ask the user to paste an API key, token, password or client secret into the chat.
- When you need one, run `secret-drop ask <NAME> <target> "<where to find it>"`. A dialog opens on
  the user's screen, the value goes straight to the target and you only see its length.
- Targets: `@<name>` (list them with `secret-drop targets`), `file:<path>`, `ssh:<host>:<path>`,
  `keychain:<service>`, `exec:<command>`. Add `--then "<command>"` to restart a service afterwards.
- For a Google OAuth refresh token run
  `secret-drop google-oauth <PREFIX> <client_id> "<scopes>" <target>`.
- Never print a secret back: no `cat`, `grep` or `echo` on files that hold secrets. Refer to secrets
  by name only.
```

## Security

**What it protects**

- **The chat transcript and the agent's context.** The value is never printed. Only its length is.
- **Shell history and the process list.** The value is never part of a command line. It reaches
  `ssh`, `security` and `exec:` commands over stdin, so `ps` and `~/.zsh_history` never contain it.
- **Files at rest.** Env files are written atomically with mode `600`, locally and remotely.
- **Mistakes before the paste.** The name and the target are validated, and ssh connectivity is
  checked, before the dialog opens, so nobody pastes a key into a dead end.
- **The OAuth redirect.** It listens on loopback only, checks `state`, uses PKCE and ignores stray
  requests.

**What it does not protect**

- **Anyone who already has access to your machine or to the target.** Env files and the keychain are
  only as safe as the account that owns them.
- **The agent reading the target afterwards.** An agent with file or shell access can still run
  `cat .env`. The instruction block above is a policy, not an enforcement mechanism. Combine it with
  your agent's permission rules (for example, deny reads of `.env` files) if that matters to you.
- **Your clipboard.** Copy-paste goes through the clipboard, so clipboard history managers keep a
  copy. Exclude them or clear the history.
- **The commands you write.** `exec:` and `--then` run what you give them.
- **Focus.** The dialog takes keyboard focus when it opens. If you were typing elsewhere, your
  keystrokes land in the hidden field. Cancel if you see dots you did not paste.

## Platforms

Tested on macOS. On Linux it falls back to `zenity` or `kdialog` if one is installed. That path is
**experimental and untested**, and the `keychain:` target is macOS only.

## Development

```bash
python3 -m unittest discover -s tests                            # no GUI needed
SECRET_DROP_TEST_KEYCHAIN=1 python3 -m unittest discover -s tests  # also writes to the login keychain, then cleans up
python3 docs/make_screenshots.py                                 # regenerate docs/ images
```

The tests replace the dialog with `SECRET_DROP_PROMPTER`, put a fake `ssh` in `PATH` that runs the
remote script locally (and records its argv, to prove the value is not in it), and run the OAuth flow
against a local fake token endpoint that verifies the PKCE verifier.

**How the images were made.** `docs/make_screenshots.py` opens the real dialog with a fake value
prefilled and captures that one window with `screencapture -l`. It renders the terminal SVGs from
real CLI output, produced with the same fake `ssh` and a fake Google token endpoint, so no real key,
host or account appears anywhere. The demo GIF was rendered with [Remotion](https://www.remotion.dev).

## License

MIT
