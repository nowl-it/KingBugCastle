#!/usr/bin/env python3
"""Extract and inject skin sprite sheets for editing.

Workflow:
  1. Extract:  python3 cli/skin_workflow.py extract <unit_id> [skin_suffix]
  2. Edit:     Edit the PNG in GIMP/Photoshop/etc
  3. Inject:   python3 cli/skin_workflow.py inject <unit_id> <skin_suffix> <edited_png>

Examples:
  python3 cli/skin_workflow.py extract 10570           # Extract default skin
  python3 cli/skin_workflow.py extract 10570 00        # Extract skin variant 00
  python3 cli/skin_workflow.py inject 10570 00 my_edit.png  # Inject edited skin

Skin suffix mapping:
  (empty) = default skin (Unit_10570)
  00 = first purchasable skin (Unit_10570_00)
  01 = second purchasable skin (Unit_10570_01)
  99_00 = default chroma variant (Unit_10570_99_00)
"""
import os
import sys
import UnityPy
from PIL import Image

from bundle_extract import extract_android_bundles

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUNDLE_DIR = "/tmp/opencode/kgc_all"
OUT_DIR = os.path.join(REPO, "server", "webui-next", "public", "assets", "skins")

def ensure_bundles():
    if os.path.isdir(BUNDLE_DIR) and os.listdir(BUNDLE_DIR):
        return
    apk_src = os.path.join(REPO, "apk", "xapk_extracted_v17201", "base_assets.apk")
    print(f"Extracting bundles from APK...")
    extract_android_bundles(apk_src, BUNDLE_DIR)

def get_texture_name(unit_id, suffix):
    """Build the texture name from unit_id and suffix."""
    if suffix:
        return f"Unit_{unit_id}_{suffix}"
    return f"Unit_{unit_id}"

def extract_skin(unit_id, suffix=""):
    """Extract a skin's sprite sheet as PNG."""
    ensure_bundles()
    env = UnityPy.load(BUNDLE_DIR)
    
    tex_name = get_texture_name(unit_id, suffix)
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            data = obj.read()
            if data.m_Name == tex_name:
                img = data.image.convert("RGBA")
                
                # Save full sprite sheet
                out_path = os.path.join(OUT_DIR, f"{tex_name}.png")
                os.makedirs(os.path.dirname(out_path), exist_ok=True)
                img.save(out_path)
                
                # Also save to /tmp for easy access
                img.save(f"/tmp/{tex_name}.png")
                
                print(f"Extracted: {tex_name}")
                print(f"  Size: {img.size[0]}x{img.size[1]} px")
                print(f"  Saved to: {out_path}")
                print(f"  Copy at: /tmp/{tex_name}.png")
                
                # Show frame info
                frame_w, frame_h = 130, 100
                cols = img.size[0] // frame_w
                rows = img.size[1] // frame_h
                print(f"  Frames: {cols}x{rows} grid ({cols*rows} frames)")
                print(f"  Frame size: {frame_w}x{frame_h} px")
                return True
    
    print(f"Error: texture '{tex_name}' not found")
    print(f"Available textures for unit {unit_id}:")
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            data = obj.read()
            if str(unit_id) in data.m_Name:
                print(f"  {data.m_Name}")
    return False

def inject_skin(unit_id, suffix, image_path):
    """Inject an edited sprite sheet back into the bundle."""
    ensure_bundles()
    
    if not os.path.isfile(image_path):
        print(f"Error: image not found: {image_path}")
        return False
    
    new_img = Image.open(image_path).convert("RGBA")
    tex_name = get_texture_name(unit_id, suffix)
    
    print(f"Injecting: {tex_name}")
    print(f"  New image: {new_img.size[0]}x{new_img.size[1]} px")
    
    env = UnityPy.load(BUNDLE_DIR)
    
    # Find and replace the texture
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            data = obj.read()
            if data.m_Name == tex_name:
                orig_size = data.image.size
                print(f"  Original: {orig_size[0]}x{orig_size[1]} px")
                
                # Resize if needed
                if new_img.size != orig_size:
                    print(f"  Resizing to {orig_size[0]}x{orig_size[1]}")
                    new_img = new_img.resize(orig_size, Image.LANCZOS)
                
                # Replace texture
                data.image = new_img
                data.save()
                
                # Save the bundle
                # Find which bundle file contains this texture
                for bundle_file in os.listdir(BUNDLE_DIR):
                    if bundle_file.endswith(".bundle"):
                        bundle_path = os.path.join(BUNDLE_DIR, bundle_file)
                        try:
                            test_env = UnityPy.load(bundle_path)
                            for test_obj in test_env.objects:
                                if test_obj.type.name == "Texture2D":
                                    test_data = test_obj.read()
                                    if test_data.m_Name == tex_name:
                                        # This is the right bundle
                                        with open(bundle_path, "wb") as f:
                                            env.file.save(f)
                                        print(f"  Saved bundle: {bundle_file}")
                                        
                                        # Save preview
                                        preview_path = os.path.join(OUT_DIR, f"{tex_name}_preview.png")
                                        new_img.save(preview_path)
                                        print(f"  Preview: {preview_path}")
                                        return True
                        except:
                            continue
                
                print("  Warning: could not find bundle file to save")
                return False
    
    print(f"Error: texture '{tex_name}' not found in bundles")
    return False

def list_skins(unit_id):
    """List all available skins for a unit."""
    ensure_bundles()
    env = UnityPy.load(BUNDLE_DIR)
    
    print(f"=== Skins for unit {unit_id} ===")
    print("\nTextures:")
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            data = obj.read()
            if str(unit_id) in data.m_Name:
                print(f"  {data.m_Name}: {data.image.size[0]}x{data.image.size[1]} px")
    
    print("\nPrefabs:")
    for obj in env.objects:
        if obj.type.name == "GameObject":
            data = obj.read()
            if data.m_Name == f"Unit_{unit_id}" or data.m_Name.startswith(f"Unit_{unit_id}_"):
                print(f"  {data.m_Name}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "extract":
        unit_id = int(sys.argv[2]) if len(sys.argv) > 2 else 10570
        suffix = sys.argv[3] if len(sys.argv) > 3 else ""
        extract_skin(unit_id, suffix)
    
    elif cmd == "inject":
        if len(sys.argv) < 5:
            print("Usage: inject <unit_id> <suffix> <image_path>")
            sys.exit(1)
        unit_id = int(sys.argv[2])
        suffix = sys.argv[3]
        image_path = sys.argv[4]
        inject_skin(unit_id, suffix, image_path)
    
    elif cmd == "list":
        unit_id = int(sys.argv[2]) if len(sys.argv) > 2 else 10570
        list_skins(unit_id)
    
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
