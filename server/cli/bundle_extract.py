"""Safe extraction of Android Addressables bundles from an APK."""
import subprocess
from pathlib import Path


def extract_android_bundles(apk_path, output_dir):
    """Extract Addressables without passing an operator-supplied path to a shell."""
    apk = Path(apk_path)
    destination = Path(output_dir)
    if not apk.is_file():
        raise FileNotFoundError(f"APK not found: {apk}")
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["unzip", "-j", "-o", str(apk), "assets/aa/Android/*", "-d", str(destination)],
        check=True,
    )
