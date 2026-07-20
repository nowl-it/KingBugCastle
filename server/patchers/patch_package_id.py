#!/usr/bin/env python3
import sys, subprocess, tempfile, shutil, pathlib, re

APK = pathlib.Path(sys.argv[1]).resolve()
OLD = sys.argv[2]
NEW = sys.argv[3]

work = pathlib.Path(tempfile.mkdtemp(prefix="pkgid_"))
dec = work / "dec"
try:
    subprocess.run(["apktool", "d", "-s", "-f", str(APK), "-o", str(dec)],
                   check=True, stdout=subprocess.DEVNULL)

    manifest = dec / "AndroidManifest.xml"
    txt = manifest.read_text(encoding="utf-8")
    
    pat = re.compile(r'(?<!android:name=")(?<!android:value=")' + re.escape(OLD))
    hits = len(pat.findall(txt))
    assert hits >= 1, f"{OLD!r} not found (outside class refs) in {manifest}"
    txt = pat.sub(NEW, txt)
    
    # Simple replacements
    reps = [
        ('<provider android:authorities="com.nowl.castle.firebaseinitprovider" android:directBootAware="true" android:exported="false" android:initOrder="100" android:name="com.google.firebase.provider.FirebaseInitProvider"/>',
         '<provider android:authorities="com.nowl.castle.firebaseinitprovider" android:directBootAware="true" android:exported="false" android:initOrder="100" android:name="com.google.firebase.provider.FirebaseInitProvider" android:enabled="false"/>'),
         
        ('<service android:enabled="true" android:exported="false" android:name="com.google.android.gms.measurement.AppMeasurementService"/>',
         '<service android:enabled="false" android:exported="false" android:name="com.google.android.gms.measurement.AppMeasurementService"/>'),
         
        ('<service android:enabled="true" android:exported="false" android:name="com.google.android.gms.measurement.AppMeasurementJobService" android:permission="android.permission.BIND_JOB_SERVICE"/>',
         '<service android:enabled="false" android:exported="false" android:name="com.google.android.gms.measurement.AppMeasurementJobService" android:permission="android.permission.BIND_JOB_SERVICE"/>'),
         
        ('<service android:enabled="true" android:exported="false" android:name="com.google.android.gms.analytics.AnalyticsService"/>',
         '<service android:enabled="false" android:exported="false" android:name="com.google.android.gms.analytics.AnalyticsService"/>'),
         
        ('<service android:enabled="true" android:exported="false" android:name="com.google.android.gms.analytics.AnalyticsJobService" android:permission="android.permission.BIND_JOB_SERVICE"/>',
         '<service android:enabled="false" android:exported="false" android:name="com.google.android.gms.analytics.AnalyticsJobService" android:permission="android.permission.BIND_JOB_SERVICE"/>'),
    ]
    for old_s, new_s in reps:
        txt = txt.replace(old_s, new_s)
        
    manifest.write_text(txt, encoding="utf-8")
    print(f"[+] {APK.name}: replaced {hits}x {OLD!r} -> {NEW!r} in AndroidManifest.xml (class refs left intact)")

    out = work / "rebuilt.apk"
    subprocess.run(["apktool", "b", str(dec), "-o", str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.copy(out, APK)
    print(f"[+] rebuilt: {APK}")
finally:
    shutil.rmtree(work, ignore_errors=True)
