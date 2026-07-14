#!/usr/bin/env python3
"""
One-shot cross-platform setup for the KGC private server.

Run once after cloning:  python3 setup.py

It: (1) checks the external tools the build needs, with per-OS install hints;
(2) extracts your game XAPK (dropped in apk/) into apk/xapk_extracted/;
(3) generates a debug keystore if you don't have one; (4) prints next steps.

No NDK / Android SDK needed - the native .so pieces ship prebuilt. Works on
Linux / macOS / Windows (the server + build are pure Python + a few Java/adb
CLI tools). redroid is Linux-only, but BlueStacks / LDPlayer / real devices
work on any OS via adb.
"""
import os, sys, shutil, subprocess, zipfile, pathlib, platform

REPO = pathlib.Path(__file__).resolve().parent
APK_DIR = REPO / "apk"
EXTRACT = APK_DIR / "xapk_extracted"
KEYSTORE = REPO / ".debug.keystore"
NEEDED_APKS = ("com.awesomepiece.castle.apk", "config.arm64_v8a.apk", "base_assets.apk")

OSX = platform.system()  # 'Linux' | 'Darwin' | 'Windows'
HINTS = {
    "Linux":   "sudo apt install apktool apksigner zipalign adb default-jre  (Debian/Ubuntu)",
    "Darwin":  "brew install apktool android-platform-tools openjdk  (zipalign/apksigner come with android-commandlinetools)",
    "Windows": "Install Android SDK build-tools (apksigner.bat/zipalign.exe) + platform-tools (adb) + apktool + a JRE; put them on PATH",
}


def ok(m):   print(f"  [ok]   {m}")
def warn(m): print(f"  [warn] {m}")
def err(m):  print(f"  [FAIL] {m}")


def check_tools():
    print("== external tools ==")
    missing = []
    # apksigner/zipalign may be .bat/.exe on Windows; check those suffixes too.
    for name in ("adb", "apktool", "apksigner", "zipalign", "java"):
        found = any(shutil.which(name + ext) for ext in ("", ".bat", ".exe", ".cmd"))
        if found:
            ok(name)
        else:
            err(name)
            missing.append(name)
    if missing:
        warn(f"install: {HINTS.get(OSX, HINTS['Linux'])}")
    return not missing


def extract_xapk():
    print("== game XAPK ==")
    if all((EXTRACT / a).exists() for a in NEEDED_APKS):
        ok(f"already extracted -> {EXTRACT}")
        return True
    xapks = sorted(APK_DIR.glob("*.xapk")) + sorted(APK_DIR.glob("*.zip"))
    if not xapks:
        err(f"no game XAPK found. Download com.awesomepiece.castle (v170.1.00, arm64) "
            f"from APKPure and drop the .xapk into {APK_DIR}/")
        APK_DIR.mkdir(exist_ok=True)
        return False
    src = xapks[0]
    ok(f"extracting {src.name} (~1GB, takes a minute)...")
    EXTRACT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        z.extractall(EXTRACT)
    have = [a for a in NEEDED_APKS if (EXTRACT / a).exists()]
    if len(have) == len(NEEDED_APKS):
        ok(f"extracted 3 split APKs -> {EXTRACT}")
        return True
    err(f"XAPK missing expected splits (got {have}). Is this the arm64 v170.1.00 XAPK?")
    return False


def gen_keystore():
    print("== signing key ==")
    home_ks = pathlib.Path.home() / ".android" / "debug.keystore"
    if KEYSTORE.exists() or home_ks.exists():
        ok("debug keystore present")
        return True
    keytool = shutil.which("keytool")
    if not keytool:
        err("keytool not found (comes with the JRE) - cannot generate a signing key")
        return False
    KEYSTORE.parent.mkdir(exist_ok=True)
    subprocess.run([keytool, "-genkeypair", "-v", "-keystore", str(KEYSTORE),
                    "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
                    "-validity", "10000", "-storepass", "android", "-keypass", "android",
                    "-dname", "CN=Android Debug,O=Android,C=US"], check=True)
    ok(f"generated {KEYSTORE}")
    return True


def gen_cert():
    print("== TLS cert (for the HTTPS :8443 listener) ==")
    cert, keyf = REPO / "server" / "cert.pem", REPO / "server" / "key.pem"
    if cert.exists() and keyf.exists():
        ok("cert.pem / key.pem present")
        return True
    # Self-signed is fine - the client's SSL-bypass patch accepts any cert.
    openssl = shutil.which("openssl")
    if openssl:
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048",
                        "-keyout", str(keyf), "-out", str(cert), "-days", "3650",
                        "-nodes", "-subj", "/CN=kgc"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok("generated self-signed cert.pem / key.pem via openssl")
        return True
    try:
        _gen_cert_py(cert, keyf)
        ok("generated self-signed cert.pem / key.pem via python cryptography")
        return True
    except Exception as e:
        warn(f"no openssl and cryptography unavailable ({e}); "
             f"generate server/cert.pem + server/key.pem manually for the :8443 listener")
        return True  # HTTP :8080 still works; TLS is only needed for the real client


def _gen_cert_py(cert, keyf):
    import datetime
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "kgc")])
    now = datetime.datetime.utcnow()
    crt = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
           .public_key(k.public_key()).serial_number(x509.random_serial_number())
           .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=3650))
           .sign(k, hashes.SHA256()))
    keyf.write_bytes(k.private_bytes(serialization.Encoding.PEM,
                     serialization.PrivateFormat.TraditionalOpenSSL,
                     serialization.NoEncryption()))
    cert.write_bytes(crt.public_bytes(serialization.Encoding.PEM))


def main():
    print(f"KGC private server setup  ({OSX})\n")
    tools = check_tools()
    xapk = extract_xapk()
    key = gen_keystore()
    gen_cert()
    print("\n== next steps ==")
    if not (tools and xapk and key):
        print("  Fix the [FAIL] items above, then re-run: python3 setup.py")
        sys.exit(1)
    print("  1. pip install -r server/requirements.txt")
    print("  2. Start server:  cd server && python3 -m uvicorn server:app --host 0.0.0.0 --port 8080")
    print("  3. Build + install the client for YOUR device - see SETUP.md")
    print("     (redroid / BlueStacks / LDPlayer / real phone all covered there).")
    print("\n  Done. See SETUP.md for device networking per target.")


if __name__ == "__main__":
    main()
