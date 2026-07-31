# server/secrets/

Credentials. **Everything in here is gitignored except this file.**

Nothing in the repo requires this directory to exist - the server starts fine without
it and just reports the affected feature as off.

| File | What it is | Read by |
|------|-----------|---------|
| `google_oauth.json` | Google OAuth **web** client, exactly as downloaded from the Cloud Console | `google_login.py` |

## google_oauth.json

Drop the file Google gives you here, unrenamed content-wise:

```json
{"web": {
  "client_id": "....apps.googleusercontent.com",
  "client_secret": "GOCSPX-...",
  "redirect_uris": ["https://your.host/glogin/callback"]
}}
```

`google_login.py` reads three things out of it: the id, the secret, and the public base
URL - which it derives from whichever `redirect_uris` entry ends in `/glogin/callback`.

That derivation is the point. The `redirect_uri` sent to Google has to byte-match one it
holds on file, and taking both from the same file removes the only way to get that wrong.
Set `GLOGIN_PUBLIC_URL` only if you deliberately want to override it.

Must be a **Web application** client. An Android or desktop ("installed") client is
rejected with an explanation, because that is exactly the kind that needs a Play Console
signing certificate - the wall this whole web flow exists to get around.

Environment variables win over the file when both are set:
`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GLOGIN_PUBLIC_URL`.
`GOOGLE_OAUTH_FILE` points at a different path.

Full setup: [`docs/multi-account-login.md`](../../docs/multi-account-login.md).

## House rules

- `chmod 600` anything you add. These are bearer credentials.
- Never paste a secret into a shell command - it lands in `~/.zsh_history` and in the
  process list, where any other user on the box can read it. That is what this
  directory is for.
- If one leaks, rotate it in the Google Cloud Console. Deleting the file is not enough;
  assume anything that was ever in git history or a shell log is public.
