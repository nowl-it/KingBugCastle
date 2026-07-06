#!/usr/bin/env python3
"""
XML Bundle Extractor for GameForge Toolkit
Extracts XML files from Unity AssetBundle using UnityPy
"""

import sys
import os

# Check if UnityPy is available
try:
    import UnityPy
except ImportError:
    print("[ERROR] UnityPy module not found. Please install it:", file=sys.stderr)
    print("[ERROR] pip install UnityPy", file=sys.stderr)
    sys.exit(1)

def main():
    # Check arguments
    if len(sys.argv) != 3:
        print("[ERROR] Usage: extract_xml.py <bundle_path> <output_dir>", file=sys.stderr)
        sys.exit(1)

    bundle_path = sys.argv[1]
    output_dir = sys.argv[2]

    # Validate bundle path
    if not os.path.exists(bundle_path):
        print(f"[ERROR] Bundle file not found: {bundle_path}", file=sys.stderr)
        sys.exit(1)

    # Create output directory
    try:
        os.makedirs(output_dir, exist_ok=True)
    except Exception as e:
        print(f"[ERROR] Failed to create output directory: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[INFO] Loading Unity bundle from: {bundle_path}")
    print(f"[INFO] Output directory: {output_dir}")

    try:
        # Load Unity bundle
        env = UnityPy.load(bundle_path)
        extracted_count = 0

        # Iterate through all TextAsset objects
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                try:
                    data = obj.read()

                    # Try to get name
                    name = str(obj.path_id)
                    try:
                        if hasattr(data, "name") and data.name:
                            name = data.name
                        elif hasattr(data, "m_Name") and data.m_Name:
                            name = data.m_Name
                    except:
                        pass

                    # Try to get script content
                    content = b""
                    try:
                        content = data.script
                    except:
                        try:
                            content = data.m_Script
                        except:
                            pass

                    if content:
                        # Convert to bytes if string
                        if isinstance(content, str):
                            content = content.encode('utf-8', 'surrogateescape')

                        # Decide extension by sniffing content. Many KGC data
                        # tables ship as plain-text (comma-separated) TextAssets,
                        # not XML (e.g. BannedKeywords, BabelStages). Keep them all.
                        ext = "bytes"
                        try:
                            head = content.lstrip(b'\xef\xbb\xbf').lstrip()
                            # Any markup start (<?xml, <!-- comment, <tag) = XML.
                            # Plain-text data tables (comma lists) never start '<'.
                            if head[:1] == b'<':
                                ext = "xml"
                            else:
                                # Valid UTF-8 text -> .txt, otherwise raw .bytes
                                content.decode('utf-8')
                                ext = "txt"
                        except Exception:
                            ext = "bytes"

                        # Avoid name collisions (duplicate m_Name in bundle)
                        base = f"{name}.{ext}"
                        filename = base
                        i = 1
                        while os.path.exists(os.path.join(output_dir, filename)):
                            filename = f"{name}_{i}.{ext}"
                            i += 1

                        filepath = os.path.join(output_dir, filename)
                        with open(filepath, "wb") as f:
                            f.write(content)

                        print(f"[EXTRACTED]{filename}")
                        extracted_count += 1

                except Exception as e:
                    print(f"[ERROR] Failed to read object: {e}", file=sys.stderr)

        if extracted_count == 0:
            print("[ERROR] No XML files found in bundle", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"[SUCCESS]{extracted_count}")
            sys.exit(0)

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
