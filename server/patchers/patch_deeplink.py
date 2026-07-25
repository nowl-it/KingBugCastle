"""Register a custom URI scheme on the launcher activity, so the Google web-login
flow can hand an account back to the app with a deep link.

The web flow (server/google_login.py) ends by navigating the browser to
`kingbugcastle://auth?id=google_<sub>`. For Android to route that back into the
app, the launcher activity needs a VIEW intent-filter for the scheme. Without it
the link opens nothing and the loop is dead.

This edits the *decoded* AndroidManifest.xml text (apktool `d -s` output), the same
string the build already rewrites for Firebase/cleartext - so it slots into the
existing decode/rebuild, no extra apktool pass.

`add_scheme(manifest_text, scheme) -> text` is pure and unit-tested below; the
build calls it between apktool d and b.
"""
import re

_FILTER = ('<intent-filter>'
           '<action android:name="android.intent.action.VIEW"/>'
           '<category android:name="android.intent.category.DEFAULT"/>'
           '<category android:name="android.intent.category.BROWSABLE"/>'
           '<data android:scheme="{scheme}"/>'
           '</intent-filter>')


def add_scheme(manifest_text, scheme="kingbugcastle"):
    """Insert a VIEW intent-filter for `scheme` into the activity that owns the
    LAUNCHER intent-filter. Idempotent: a manifest already carrying the scheme is
    returned unchanged. Raises if no launcher activity is found - failing loud beats
    shipping an APK the deep link silently can't reach."""
    if f'android:scheme="{scheme}"' in manifest_text:
        return manifest_text

    # Find each <activity ...>...</activity> and pick the one declaring LAUNCHER.
    for m in re.finditer(r"<activity\b.*?</activity>", manifest_text, re.DOTALL):
        block = m.group(0)
        if "android.intent.category.LAUNCHER" not in block:
            continue
        new_block = block.replace("</activity>",
                                  _FILTER.format(scheme=scheme) + "</activity>", 1)
        return manifest_text[:m.start()] + new_block + manifest_text[m.end():]

    raise RuntimeError("no launcher activity in the manifest - cannot register the "
                       "deep-link scheme")


if __name__ == "__main__":   # self-check
    SAMPLE = (
        '<manifest><application>'
        '<activity android:name="co.ab180.airbridge.unity.AirbridgeActivity">'
        '<intent-filter>'
        '<action android:name="android.intent.action.MAIN"/>'
        '<category android:name="android.intent.category.LAUNCHER"/>'
        '</intent-filter></activity>'
        '<activity android:name="com.unity3d.player.UnityPlayerActivity"/>'
        '</application></manifest>')

    out = add_scheme(SAMPLE, "kingbugcastle")
    assert 'android:scheme="kingbugcastle"' in out
    # It landed inside the launcher activity, not the other one.
    launcher = re.search(r'AirbridgeActivity.*?</activity>', out, re.DOTALL).group(0)
    assert 'android:scheme="kingbugcastle"' in launcher, "scheme not in launcher activity"
    other = re.search(r'UnityPlayerActivity[^>]*/>', out).group(0)
    assert "scheme" not in other
    assert "BROWSABLE" in out and "action.VIEW" in out
    # Idempotent.
    assert add_scheme(out, "kingbugcastle") == out, "second pass changed the manifest"
    # No launcher -> loud failure.
    try:
        add_scheme('<manifest><application></application></manifest>')
        assert False, "expected RuntimeError with no launcher activity"
    except RuntimeError:
        pass
    print("patch_deeplink self-check ok")
