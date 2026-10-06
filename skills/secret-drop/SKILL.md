---
name: secret-drop
description: Use whenever a task needs an API key, token, password, client secret or OAuth refresh token, or needs to run something with credentials. Never ask the user to paste a secret into the chat; secret-drop opens a native dialog on their screen, writes the value straight to its destination (env file, keychain, server over ssh, CI via a command) and only reports its length.
---

# secret-drop

Secrets never go through the chat, the terminal or your context. The user types them into a native
dialog; you only ever see names and lengths.

## Rules

- Never ask the user to paste a secret into the chat, and never put one on a command line.
- Never read secret files or the keychain (`cat .env`, `grep`, the Read tool, `security ... -w`).
  The secret-drop guard blocks those calls; when it does, use the commands below instead.
- Refer to secrets by name only. Never print, echo or log them.

## Get a secret from the user

```bash
secret-drop ask NAME TARGET "where to find it"
```

A dialog opens on the user's screen. Tell them it is there. Exit codes: `0` saved, `1` the user cancelled or
the dialog timed out (ask whether to retry, don't loop), `2` bad usage, `3` the dialog could not open (if you
run in a sandbox, rerun the same command with elevated permissions), `4` anything else failed (read the message).

Pick the target:

| Situation | Target |
|---|---|
| A configured destination exists (`secret-drop targets` lists them) | `@name` |
| Best default on macOS: value in the Keychain, `.env` keeps a reference that is safe to read | `keychain:<project> --ref .env` |
| Plain env file in the project | `file:.env` (added to `.gitignore` automatically) |
| Env file on a server | `ssh:<host>:<path>`, add `--then "ssh <host> sudo systemctl restart <service>"` |
| Anything that reads stdin (GitHub Actions secret, cloud secret manager) | `exec:<command>`; the name is in `$SECRET_DROP_NAME` |

The hint is the third argument: say exactly where the value lives, e.g. `"Stripe Dashboard → Developers → API keys"`.

## Use secrets

```bash
secret-drop run -f .env -- npm run deploy
```

`run` loads the file (resolving `keychain:` references) into the command's environment and replaces
any secret value in its output with `[redacted:NAME]`. Prefer it over `source .env` or `export`.

## See what exists

```bash
secret-drop list file:.env      # names only; keychain references are shown, values never
secret-drop list keychain:myapp
secret-drop targets             # configured @destinations
```

## Google OAuth refresh token

```bash
secret-drop google-oauth PREFIX CLIENT_ID "SCOPES" TARGET [--no-open]
```

Needs an OAuth client of type "Desktop app". It asks for the client secret in the dialog, opens the
consent screen (or prints `AUTH_URL ...` with `--no-open`; pass it to the user) and stores
`PREFIX_CLIENT_ID`, `PREFIX_CLIENT_SECRET` and `PREFIX_REFRESH_TOKEN`. Use `--reuse-secret` to
re-authorize with the stored client secret.
