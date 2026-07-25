# Multiple accounts, multiple devices, and Google login

## What "one account only" was

The server keyed every request on the *active* save unless `KGC_MULTIPLAYER=1`
was set, and that env var was off by default. So two devices, or two logins on
one device, both landed on the same save. The machinery to give each login its
own save existed - it was just switched off.

## What changed

`KGC_MULTIPLAYER` now defaults **on**. Each login id gets its own save, and the
same id restores the same save on any device. Set `KGC_MULTIPLAYER=0` to force
the old single-shared-save behaviour.

### How a login maps to a save

`/auth/register` sends `{ type, id, userName, ... }`; `/auth/auth?id=` re-presents
the same id; `/auth/login` re-presents a session token, not an id. The server
resolves, in order:

1. **Known account id** -> its save (`accounts` table, `login_id -> uid`).
2. **A presented session token** -> the save that token was bound to at login
   (`sessions` table, 7-day TTL).
3. **First-login adoption** -> if the server has been single-player until now
   (exactly one save, zero bound accounts), the first login *adopts* that save
   instead of getting a fresh empty one. This is the migration path: your one
   existing save becomes account #1 rather than being orphaned. It fires once.
4. **A fresh per-account save** -> `uid = "p-" + sha1(id)[:12]`, seeded from
   `default_player.json`. Capped at `KGC_MAX_PLAYERS` (default 200), because the
   id is client-supplied and unauthenticated.

`Constants.AccountType` (from the client): `0` Test, `1` Google, `2` GameCenter,
`3` AppleID, `4` Guest. The register `type` is stored on the save so
`PlayerDataResponseModel.accountType` reports the right badge.

## Google login

The value of a Google (or Apple) login over a Guest login is a **stable id**: a
Guest id is generated locally and regenerated when the app is reinstalled with a
cleared cache, so a Guest save is effectively device-local and lost on reinstall.
A Google id is the same account forever, so the same Google login on a new device
restores the same save. The server treats it exactly like any other id - once the
client hands over a Google account id, cross-device restore just works.

### The client-side catch (be honest about this)

Real Google Play Games sign-in only authenticates an app whose **package name and
signing certificate are registered in the Google Play Console** under an OAuth
client. Our repackaged build (`com.nowl.castle`, signed with the debug keystore)
is not registered, so the in-game **Google button fails inside the Google SDK,
before any request reaches this server.** There is no server-side fix for that -
it is Google refusing to vouch for an app it doesn't recognise.

So on a repacked private build, real Google sign-in is not available. It works:

- on the genuine app, or
- on a build you registered yourself in a Google Play Console project (your own
  package id + your keystore's SHA-1 + an OAuth client, and the GPGS app id baked
  into the APK).

### What works cross-device on the repacked build today

- **Guest per device** - each device generates its own Guest id and gets its own
  save. Good for "several independent players", not for "the same player on two
  devices" (Guest ids differ per device).
- **Account transfer code** - the same-player-across-devices path that needs no
  Google. Device A calls `/transfer/issue` to mint a short code (24 h TTL); device
  B enters it via the in-game transfer UI (`/transfer/redeem`), which binds B's
  login to A's save. This is implemented and is the recommended cross-device flow
  for private builds.

## Tests

- `server/tests/test_multi_login.py` - adoption, per-account isolation, same-id
  cross-device restore, type capture, and the `KGC_MULTIPLAYER=0` override.
- `server/tests/test_multi_account.py` - boards/matchmaking/other-player across
  accounts.
- `server/tests/test_identity_routing.py` - the token -> uid request routing.
