#!/usr/bin/env python3
"""Add the Frieren skin as a separate Farael asset set.

The source skin (1057002 / Unit_10570_02) is never edited. Instead this tool
clones its sprite sheet, Sprite sub-assets, prefab hierarchy, and illustration
to Unit_10570_03, then replaces only the cloned textures. It also clones the
five Addressables locations that expose those objects to the client.

The private build patches AssetBundleRequestOptions CRC reads to zero, so the
modified bundles do not require catalog CRC rewrites.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import io
import json
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import UnityPy
from PIL import Image, ImageChops, ImageStat


REPO = Path(__file__).resolve().parents[2]
DEFAULT_APK = REPO / "apk/xapk_extracted_v17201/base_assets.apk"
DEFAULT_XAPK = REPO / "apk/com.awesomepiece.castle@172.0.01.xapk"

SPRITES_BUNDLE = "assets/aa/Android/sprites_assets_all_6b5da89c84311657fd1bce86b389add4.bundle"
ILLUSTS_BUNDLE = "assets/aa/Android/illusts_assets_all_51d47e782f5b75edd56eb09a7dd37fae.bundle"
CHARACTERS_BUNDLE = "assets/aa/Android/characters_assets_all_5a580f4a7414e9b895849369795f87bb.bundle"
CATALOG_PATH = "assets/aa/catalog.json"

SOURCE = "Unit_10570_02"
TARGET = "Unit_10570_03"
SOURCE_ILLUST = "Unit_Illust_10570_02"
TARGET_ILLUST = "Unit_Illust_10570_03"

SOURCE_SPRITE_PATH = "Assets/00_Unit/#Image/Unit_10570_02.png"
TARGET_SPRITE_PATH = "Assets/00_Unit/#Image/Unit_10570_03.png"
SOURCE_ILLUST_PATH = "Assets/04_Artwork/Illusts/Unit_Illust_10570_02.png"
TARGET_ILLUST_PATH = "Assets/04_Artwork/Illusts/Unit_Illust_10570_03.png"
SOURCE_PREFAB_PATH = "Assets/00_Unit/1_Hero/Unit_10570_02.prefab"
TARGET_PREFAB_PATH = "Assets/00_Unit/1_Hero/Unit_10570_03.prefab"

SPRITE_IMAGE = REPO / "server/assets/frieren/Unit_10570_03.png"
ILLUST_IMAGE = REPO / "server/assets/frieren/Unit_Illust_10570_03.png"

# These are prefab-instance objects. Animations, materials, MonoScripts,
# shadow sprites, and the AnimatorController are immutable shared assets.
PREFAB_CLONE_TYPES = {
    "AnimationClip",
    "Animator",
    "AnimatorController",
    "GameObject",
    "MonoBehaviour",
    "SpriteRenderer",
    "Transform",
}

# ContentCatalogData 1.21 stores each location as seven little-endian int32s:
# internalId, provider, dependencyKey, dependencyHash, extraData, primaryKey,
# resourceType. These source locations are cloned with only internalId and
# primaryKey changed; their bundle dependency and runtime type stay intact.
CATALOG_CLONES = (
    (SOURCE_SPRITE_PATH, TARGET_SPRITE_PATH, SOURCE, TARGET, 2),
    (
        SOURCE_PREFAB_PATH,
        TARGET_PREFAB_PATH,
        f"Character_{SOURCE}",
        f"Character_{TARGET}",
        1,
    ),
    # Keep the new portrait in the sprites bundle.  ResourceSkin ultimately
    # falls back to SimpleAssetDB.GetSprite(), and the independently cloned
    # sprite/prefab assets prove this dependency is available when the skin
    # panel asks for it.  The original dedicated illusts bundle is left
    # byte-for-byte pristine; only its Sprite import geometry is used as the
    # template for the cloned portrait.
    (SOURCE_SPRITE_PATH, TARGET_ILLUST_PATH, SOURCE, TARGET_ILLUST, 2),
)


def _read_i32(data: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def _read_catalog_key(key_data: bytes, offset: int) -> Any:
    """Read the compact key types used by this catalog."""
    key_type = key_data[offset]
    offset += 1
    if key_type in (0, 1):  # ASCIIString / UnicodeString
        length = _read_i32(key_data, offset)
        raw = key_data[offset + 4 : offset + 4 + length]
        return raw.decode("ascii" if key_type == 0 else "utf-16-le")
    if key_type == 2:
        return struct.unpack_from("<H", key_data, offset)[0]
    if key_type == 3:
        return struct.unpack_from("<I", key_data, offset)[0]
    if key_type == 4:
        return _read_i32(key_data, offset)
    if key_type in (5, 6):  # Hash128 / Type GUID
        length = key_data[offset]
        raw = key_data[offset + 1 : offset + 1 + length]
        return ("hash" if key_type == 5 else "type", raw)
    if key_type == 7:
        return ("json", offset)
    raise RuntimeError(f"Unsupported Addressables key type {key_type}")


def _catalog_tables(catalog: dict[str, Any]) -> tuple[
    bytes, list[Any], list[tuple[int, list[int]]], list[tuple[int, ...]]
]:
    key_data = base64.b64decode(catalog["m_KeyDataString"])
    bucket_data = base64.b64decode(catalog["m_BucketDataString"])
    entry_data = base64.b64decode(catalog["m_EntryDataString"])

    key_count = _read_i32(key_data, 0)
    bucket_count = _read_i32(bucket_data, 0)
    if key_count != bucket_count:
        raise RuntimeError(
            f"Catalog key/bucket count mismatch: {key_count} != {bucket_count}"
        )

    keys: list[Any] = []
    buckets: list[tuple[int, list[int]]] = []
    offset = 4
    for _ in range(bucket_count):
        key_offset = _read_i32(bucket_data, offset)
        entry_count = _read_i32(bucket_data, offset + 4)
        entry_indices = [
            _read_i32(bucket_data, offset + 8 + index * 4)
            for index in range(entry_count)
        ]
        keys.append(_read_catalog_key(key_data, key_offset))
        buckets.append((key_offset, entry_indices))
        offset += 8 + entry_count * 4
    if offset != len(bucket_data):
        raise RuntimeError("Catalog bucket table has trailing or truncated data")

    entry_count = _read_i32(entry_data, 0)
    expected_size = 4 + entry_count * 28
    if len(entry_data) != expected_size:
        raise RuntimeError(
            f"Catalog entry table size mismatch: {len(entry_data)} != {expected_size}"
        )
    entries = [
        struct.unpack_from("<7i", entry_data, 4 + index * 28)
        for index in range(entry_count)
    ]
    return key_data, keys, buckets, entries


def _patch_catalog(raw: bytes) -> bytes:
    """Clone the source skin's five compact Addressables locations."""
    catalog = json.loads(raw)
    key_data_raw, keys, buckets, entries = _catalog_tables(catalog)
    key_data = bytearray(key_data_raw)
    internal_ids: list[str] = catalog["m_InternalIds"]

    for source_path, target_path, source_key, target_key, expected_count in CATALOG_CLONES:
        if target_path in internal_ids or target_key in keys:
            raise RuntimeError(f"Catalog target already exists: {target_key}")

        source_indices = [
            index
            for index, entry in enumerate(entries)
            if internal_ids[entry[0]] == source_path and keys[entry[5]] == source_key
        ]
        if len(source_indices) != expected_count:
            raise RuntimeError(
                f"Expected {expected_count} catalog locations for {source_key}, "
                f"found {source_indices}"
            )

        target_internal_id = len(internal_ids)
        internal_ids.append(target_path)

        encoded_key = target_key.encode("ascii")
        target_key_offset = len(key_data)
        key_data.extend(b"\x00")  # SerializationUtilities.ObjectType.AsciiString
        key_data.extend(struct.pack("<i", len(encoded_key)))
        key_data.extend(encoded_key)
        target_key_index = len(keys)
        keys.append(target_key)

        target_entries: list[int] = []
        for source_index in source_indices:
            clone = list(entries[source_index])
            clone[0] = target_internal_id
            clone[5] = target_key_index
            target_entries.append(len(entries))
            entries.append(tuple(clone))
        buckets.append((target_key_offset, target_entries))
        print(
            f"Catalog: {source_key} -> {target_key} "
            f"({len(target_entries)} location{'s' if len(target_entries) != 1 else ''})"
        )

    struct.pack_into("<i", key_data, 0, len(keys))

    bucket_data = bytearray(struct.pack("<i", len(buckets)))
    for key_offset, entry_indices in buckets:
        bucket_data.extend(struct.pack("<ii", key_offset, len(entry_indices)))
        for entry_index in entry_indices:
            bucket_data.extend(struct.pack("<i", entry_index))

    entry_data = bytearray(struct.pack("<i", len(entries)))
    for entry in entries:
        entry_data.extend(struct.pack("<7i", *entry))

    catalog["m_KeyDataString"] = base64.b64encode(key_data).decode("ascii")
    catalog["m_BucketDataString"] = base64.b64encode(bucket_data).decode("ascii")
    catalog["m_EntryDataString"] = base64.b64encode(entry_data).decode("ascii")
    return json.dumps(catalog, separators=(",", ":"), ensure_ascii=False).encode()


def _path_id(namespace: str, old_path_id: int, occupied: set[int]) -> int:
    """Generate a deterministic signed int64 path ID and avoid collisions."""
    salt = 0
    while True:
        seed = f"kgc-frieren-v1:{namespace}:{old_path_id}:{salt}".encode()
        candidate = int.from_bytes(
            hashlib.blake2b(seed, digest_size=8).digest(), "little", signed=True
        )
        if candidate not in occupied and candidate not in (0, 1):
            occupied.add(candidate)
            return candidate
        salt += 1


def _render_data_guid(namespace: str) -> dict[str, int]:
    """Generate the four uint32 words used by Sprite.m_RenderDataKey."""
    digest = hashlib.blake2s(
        f"kgc-frieren-render-v1:{namespace}".encode(), digest_size=16
    ).digest()
    return {
        f"data[{index}]": struct.unpack_from("<I", digest, index * 4)[0]
        for index in range(4)
    }


def _copy_pptr(pointer: Any, path_id: int | None = None) -> Any:
    result = copy.copy(pointer)
    if path_id is not None:
        result.m_PathID = path_id
    return result


def _rewrite_tree(
    value: Any,
    *,
    local_paths: dict[int, int] | None = None,
    external_paths: dict[int, int] | None = None,
    source_name: str | None = None,
    target_name: str | None = None,
) -> Any:
    """Rewrite names and PPtrs inside a typetree represented as dict/list."""
    local_paths = local_paths or {}
    external_paths = external_paths or {}
    if isinstance(value, dict):
        if "m_FileID" in value and "m_PathID" in value:
            file_id = value["m_FileID"]
            path_id = value["m_PathID"]
            if file_id == 0 and path_id in local_paths:
                value["m_PathID"] = local_paths[path_id]
            elif file_id != 0 and path_id in external_paths:
                value["m_PathID"] = external_paths[path_id]
        for key, child in value.items():
            value[key] = _rewrite_tree(
                child,
                local_paths=local_paths,
                external_paths=external_paths,
                source_name=source_name,
                target_name=target_name,
            )
        return value
    if isinstance(value, list):
        for index, child in enumerate(value):
            value[index] = _rewrite_tree(
                child,
                local_paths=local_paths,
                external_paths=external_paths,
                source_name=source_name,
                target_name=target_name,
            )
        return value
    if isinstance(value, tuple):
        return tuple(
            _rewrite_tree(
                child,
                local_paths=local_paths,
                external_paths=external_paths,
                source_name=source_name,
                target_name=target_name,
            )
            for child in value
        )
    if isinstance(value, str) and source_name and target_name:
        return value.replace(source_name, target_name)
    return value


def _clone_reader(source: Any, path_id: int, tree: dict[str, Any]) -> Any:
    clone = copy.copy(source)
    clone.path_id = path_id
    clone.data = source.get_raw_data()
    clone._read_until = None
    source.assets_file.objects[path_id] = clone
    clone.save_typetree(tree)
    return clone


def _asset_bundle(env: Any) -> tuple[Any, Any]:
    object_reader = next(obj for obj in env.objects if obj.type.name == "AssetBundle")
    return object_reader, object_reader.read()


def _container_rows(asset_bundle: Any, path: str) -> list[tuple[str, Any]]:
    rows = [(key, info) for key, info in asset_bundle.m_Container if key == path]
    if not rows:
        raise RuntimeError(f"AssetBundle container entry missing: {path}")
    return rows


def _append_container_group(
    asset_bundle: Any,
    source_rows: list[tuple[str, Any]],
    target_path: str,
    path_map: dict[int, int],
) -> None:
    source_info = source_rows[0][1]
    start = len(asset_bundle.m_PreloadTable)
    source_preloads = asset_bundle.m_PreloadTable[
        source_info.preloadIndex : source_info.preloadIndex + source_info.preloadSize
    ]
    for pointer in source_preloads:
        asset_bundle.m_PreloadTable.append(
            _copy_pptr(pointer, path_map.get(pointer.m_PathID, pointer.m_PathID))
        )

    for _, source_row_info in source_rows:
        info = copy.copy(source_row_info)
        info.asset = _copy_pptr(
            source_row_info.asset,
            path_map.get(source_row_info.asset.m_PathID, source_row_info.asset.m_PathID),
        )
        info.preloadIndex = start
        info.preloadSize = len(source_preloads)
        asset_bundle.m_Container.append((target_path, info))

    # Unity writes this collection sorted by asset path. Python's sort is
    # stable, retaining Texture2D/Sprite order among duplicate paths.
    asset_bundle.m_Container.sort(key=lambda row: row[0])


def _clone_texture_group(
    raw: bytes,
    *,
    source_path: str,
    target_path: str,
    source_name: str,
    target_name: str,
    replacement_path: Path,
    namespace: str,
) -> tuple[bytes, dict[int, int], str]:
    env = UnityPy.load(io.BytesIO(raw))
    bundle_reader, asset_bundle = _asset_bundle(env)
    rows = _container_rows(asset_bundle, source_path)
    assets_file = bundle_reader.assets_file
    occupied = set(assets_file.objects)
    source_ids = [row[1].asset.m_PathID for row in rows]
    path_map = {
        source_id: _path_id(namespace, source_id, occupied) for source_id in source_ids
    }

    original_texture_hash = ""
    replacement = Image.open(replacement_path).convert("RGBA")
    for source_id in source_ids:
        source = assets_file.objects[source_id]
        target_id = path_map[source_id]
        if source.type.name == "Texture2D":
            texture = source.read()
            if texture.m_Name != source_name:
                raise RuntimeError(
                    f"Unexpected texture {texture.m_Name!r} in {source_path}"
                )
            original_texture_hash = hashlib.sha256(
                texture.image.convert("RGBA").tobytes()
            ).hexdigest()
            clone = copy.copy(source)
            clone.path_id = target_id
            clone.data = source.get_raw_data()
            clone._read_until = None
            assets_file.objects[target_id] = clone
            texture.set_object_reader(clone)
            texture.m_Name = target_name
            texture.image = replacement.resize(
                (texture.m_Width, texture.m_Height), Image.Resampling.LANCZOS
            )
            texture.save()
        else:
            tree = copy.deepcopy(source.read_typetree())
            tree = _rewrite_tree(
                tree,
                local_paths=path_map,
                source_name=source_name,
                target_name=target_name,
            )
            if source.type.name == "Sprite":
                # A cloned Sprite cannot retain the source asset GUID. Unity
                # uses this key in its Sprite render-data lookup; duplicate
                # keys can resolve the source skin or produce an empty image.
                tree["m_RenderDataKey"] = (
                    _render_data_guid(namespace),
                    tree["m_RenderDataKey"][1],
                )
                if source_name in (SOURCE, SOURCE_ILLUST):
                    _set_full_rect_sprite(tree)
            _clone_reader(source, target_id, tree)

    _append_container_group(asset_bundle, rows, target_path, path_map)
    asset_bundle.save()
    return bundle_reader.assets_file.parent.save(packer="original"), path_map, original_texture_hash


def _clone_illust_into_sprites_bundle(
    raw: bytes,
    *,
    replacement_path: Path,
    source_illust_tree: dict[str, Any],
) -> bytes:
    """Create the target portrait inside the already-working sprites bundle.

    The previous build appended the portrait to the dedicated illusts bundle.
    Its serialized objects were valid in offline UnityPy checks, but
    ``Utility.LoadIllust`` could not locate the new key at runtime.  Character
    sprites in this bundle do resolve through the same SimpleAssetDB path, so
    use it as the target portrait's Addressables dependency while retaining
    the official illustration Sprite's pivot/import settings.
    """
    env = UnityPy.load(io.BytesIO(raw))
    bundle_reader, asset_bundle = _asset_bundle(env)
    assets_file = bundle_reader.assets_file
    source_rows = _container_rows(asset_bundle, SOURCE_SPRITE_PATH)
    occupied = set(assets_file.objects)

    source_texture_reader = next(
        obj
        for obj in env.objects
        if obj.type.name == "Texture2D" and obj.peek_name() == SOURCE
    )
    source_frame_reader = next(
        obj
        for obj in env.objects
        if obj.type.name == "Sprite" and obj.peek_name() == f"{SOURCE}_18"
    )
    texture_id = _path_id("illust-in-sprites-texture", source_texture_reader.path_id, occupied)
    sprite_id = _path_id("illust-in-sprites-sprite", source_frame_reader.path_id, occupied)

    texture_clone = copy.copy(source_texture_reader)
    texture_clone.path_id = texture_id
    texture_clone.data = source_texture_reader.get_raw_data()
    texture_clone._read_until = None
    assets_file.objects[texture_id] = texture_clone
    texture = source_texture_reader.read()
    texture.set_object_reader(texture_clone)
    texture.m_Name = TARGET_ILLUST
    replacement = Image.open(replacement_path).convert("RGBA")
    texture.image = replacement.resize((1024, 1024), Image.Resampling.LANCZOS)
    texture.save()

    sprite_tree = copy.deepcopy(source_illust_tree)
    sprite_tree["m_Name"] = TARGET_ILLUST
    sprite_tree["m_RenderDataKey"] = (
        _render_data_guid("illust-in-sprites"),
        sprite_tree["m_RenderDataKey"][1],
    )
    sprite_tree["m_RD"]["texture"] = {"m_FileID": 0, "m_PathID": texture_id}
    _set_full_rect_sprite(sprite_tree)
    _clone_reader(source_frame_reader, sprite_id, sprite_tree)

    def template_row(type_name: str, sprite_name: str | None = None) -> Any:
        for _, info in source_rows:
            reader = assets_file.objects.get(info.asset.m_PathID)
            if reader is None or reader.type.name != type_name:
                continue
            if sprite_name is not None and reader.peek_name() != sprite_name:
                continue
            return info
        raise RuntimeError(f"No {type_name} container template in {SOURCE_SPRITE_PATH}")

    texture_info = copy.copy(template_row("Texture2D"))
    sprite_info = copy.copy(template_row("Sprite", f"{SOURCE}_18"))
    start = len(asset_bundle.m_PreloadTable)
    texture_pointer = _copy_pptr(texture_info.asset, texture_id)
    sprite_pointer = _copy_pptr(sprite_info.asset, sprite_id)
    asset_bundle.m_PreloadTable.extend((texture_pointer, sprite_pointer))
    for info, pointer in ((texture_info, texture_pointer), (sprite_info, sprite_pointer)):
        info.asset = pointer
        info.preloadIndex = start
        info.preloadSize = 2
        asset_bundle.m_Container.append((TARGET_ILLUST_PATH, info))
    asset_bundle.m_Container.sort(key=lambda row: row[0])
    asset_bundle.save()
    return bundle_reader.assets_file.parent.save(packer="original")


def _set_full_rect_sprite(tree: dict[str, Any]) -> None:
    """Replace a cloned tight Sprite mesh with a four-vertex cell quad.

    Farael's source Sprites were imported with tight packing.  Their
    ``textureRect`` and polygon vertices follow Farael's silhouette rather
    than the declared 130x140 ``m_Rect``.  Reusing that geometry crops a new
    character and then stretches the crop to the original sprite size.  The
    cloned skin instead renders its entire declared cell while retaining the
    original pivot and pixels-per-unit.
    """
    rect = tree["m_Rect"]
    pivot = tree["m_Pivot"]
    pixels_to_units = tree["m_PixelsToUnits"]
    render_data = tree["m_RD"]

    left = -rect["width"] * pivot["x"] / pixels_to_units
    right = rect["width"] * (1.0 - pivot["x"]) / pixels_to_units
    bottom = -rect["height"] * pivot["y"] / pixels_to_units
    top = rect["height"] * (1.0 - pivot["y"]) / pixels_to_units
    vertices = (
        (left, top, 0.0),
        (right, top, 0.0),
        (left, bottom, 0.0),
        (right, bottom, 0.0),
    )

    render_data["textureRect"] = copy.deepcopy(rect)
    render_data["textureRectOffset"] = {"x": 0.0, "y": 0.0}
    render_data["settingsRaw"] = 0  # rectangle packing + full-rect mesh
    render_data["uvTransform"] = {
        "x": pixels_to_units,
        "y": rect["x"] + rect["width"] * pivot["x"],
        "z": pixels_to_units,
        "w": rect["y"] + rect["height"] * pivot["y"],
    }
    render_data["m_SubMeshes"] = [
        {
            "firstByte": 0,
            "indexCount": 6,
            "topology": 0,
            "baseVertex": 0,
            "firstVertex": 0,
            "vertexCount": 4,
            "localAABB": {
                "m_Center": {"x": 0.0, "y": 0.0, "z": 0.0},
                "m_Extent": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        }
    ]
    # Two clockwise triangles.  Unity serializes Sprite indices as raw bytes.
    render_data["m_IndexBuffer"] = [0, 0, 1, 0, 2, 0, 2, 0, 1, 0, 3, 0]
    vertex_data = render_data["m_VertexData"]
    vertex_data["m_VertexCount"] = 4
    vertex_data["m_DataSize"] = b"".join(
        struct.pack("<3f", *vertex) for vertex in vertices
    ) + b"\x00" * 32


def _clone_prefab(
    raw: bytes,
    *,
    sprite_paths: dict[int, int],
) -> tuple[bytes, dict[int, int]]:
    env = UnityPy.load(io.BytesIO(raw))
    bundle_reader, asset_bundle = _asset_bundle(env)
    rows = _container_rows(asset_bundle, SOURCE_PREFAB_PATH)
    if len(rows) != 1:
        raise RuntimeError(f"Expected one prefab row, found {len(rows)}")
    source_info = rows[0][1]
    assets_file = bundle_reader.assets_file
    source_preloads = asset_bundle.m_PreloadTable[
        source_info.preloadIndex : source_info.preloadIndex + source_info.preloadSize
    ]

    occupied = set(assets_file.objects)
    clone_sources = [
        assets_file.objects[pointer.m_PathID]
        for pointer in source_preloads
        if pointer.m_FileID == 0
        and assets_file.objects[pointer.m_PathID].type.name in PREFAB_CLONE_TYPES
    ]
    local_paths = {
        source.path_id: _path_id("prefab", source.path_id, occupied)
        for source in clone_sources
    }

    for source in clone_sources:
        tree = copy.deepcopy(source.read_typetree())
        tree = _rewrite_tree(
            tree,
            local_paths=local_paths,
            external_paths=sprite_paths,
            source_name=SOURCE,
            target_name=TARGET,
        )
        _clone_reader(source, local_paths[source.path_id], tree)

    combined_paths = dict(sprite_paths)
    combined_paths.update(local_paths)
    _append_container_group(asset_bundle, rows, TARGET_PREFAB_PATH, combined_paths)

    # _append_container_group cannot distinguish same-file from external PPtrs.
    # Rebuild only the newly appended prefab preload slice with file-aware maps.
    start = len(asset_bundle.m_PreloadTable) - len(source_preloads)
    corrected = []
    for pointer in source_preloads:
        new_id = pointer.m_PathID
        if pointer.m_FileID == 0:
            new_id = local_paths.get(new_id, new_id)
        else:
            new_id = sprite_paths.get(new_id, new_id)
        corrected.append(_copy_pptr(pointer, new_id))
    asset_bundle.m_PreloadTable[start:] = corrected

    asset_bundle.save()
    return bundle_reader.assets_file.parent.save(packer="original"), local_paths


def _restore_pristine_base_assets(xapk: Path, apk: Path) -> None:
    with zipfile.ZipFile(xapk) as archive:
        members = [name for name in archive.namelist() if Path(name).name == "base_assets.apk"]
        if len(members) != 1:
            raise RuntimeError(f"Expected one base_assets.apk in {xapk}, found {members}")
        apk.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=apk.parent, suffix=".apk", delete=False) as temp:
            temp_path = Path(temp.name)
            with archive.open(members[0]) as source:
                shutil.copyfileobj(source, temp, length=16 * 1024 * 1024)
    shutil.move(temp_path, apk)
    print(f"Restored pristine base_assets.apk ({apk.stat().st_size:,} bytes)")


def _replace_zip_members(apk: Path, replacements: dict[str, bytes]) -> None:
    with tempfile.NamedTemporaryFile(dir=apk.parent, suffix=".apk", delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        with zipfile.ZipFile(apk) as source, zipfile.ZipFile(temp_path, "w") as dest:
            for info in source.infolist():
                data = replacements.get(info.filename)
                if data is None:
                    data = source.read(info.filename)
                dest.writestr(info, data)
        shutil.move(temp_path, apk)
    finally:
        temp_path.unlink(missing_ok=True)


def _texture(env: Any, name: str) -> Any:
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            texture = obj.read()
            if texture.m_Name == name:
                return texture
    raise RuntimeError(f"Texture2D missing after write: {name}")


def _verify(
    apk: Path,
    original_sprite_hash: str,
    original_illust_hash: str,
    sprite_paths: dict[int, int],
) -> None:
    with zipfile.ZipFile(apk) as archive:
        catalog = json.loads(archive.read(CATALOG_PATH))
        _, keys, buckets, entries = _catalog_tables(catalog)
        locations_by_key = {
            keys[index]: entry_indices
            for index, (_, entry_indices) in enumerate(buckets)
        }
        for _, target_path, _, target_key, expected_count in CATALOG_CLONES:
            location_indices = locations_by_key.get(target_key, [])
            if len(location_indices) != expected_count:
                raise RuntimeError(
                    f"Addressables key {target_key} has {len(location_indices)} "
                    f"locations, expected {expected_count}"
                )
            resolved_paths = {
                catalog["m_InternalIds"][entries[index][0]]
                for index in location_indices
            }
            if resolved_paths != {target_path}:
                raise RuntimeError(
                    f"Addressables key {target_key} resolves to {resolved_paths}"
                )

        sprites = UnityPy.load(io.BytesIO(archive.read(SPRITES_BUNDLE)))
        old_sprite = _texture(sprites, SOURCE)
        new_sprite = _texture(sprites, TARGET)
        old_sprite_hash = hashlib.sha256(
            old_sprite.image.convert("RGBA").tobytes()
        ).hexdigest()
        if old_sprite_hash != original_sprite_hash:
            raise RuntimeError("Original Unit_10570_02 texture changed")
        expected_sprite = Image.open(SPRITE_IMAGE).convert("RGBA").resize(
            new_sprite.image.size, Image.Resampling.LANCZOS
        )
        sprite_exact = ImageChops.difference(
            new_sprite.image.convert("RGBA"), expected_sprite
        ).getbbox() is None

        source_frame = next(
            obj.read_typetree()
            for obj in sprites.objects
            if obj.type.name == "Sprite" and obj.read().m_Name == f"{SOURCE}_18"
        )
        target_frame = next(
            obj.read_typetree()
            for obj in sprites.objects
            if obj.type.name == "Sprite" and obj.read().m_Name == f"{TARGET}_18"
        )
        if target_frame["m_RD"]["texture"]["m_PathID"] not in sprite_paths.values():
            raise RuntimeError("Unit_10570_03_18 still references the original texture")
        if target_frame["m_RenderDataKey"][0] == source_frame["m_RenderDataKey"][0]:
            raise RuntimeError("Unit_10570_03 sprites still share the source render GUID")

        target_frames = [
            obj
            for obj in sprites.objects
            if obj.type.name == "Sprite"
            and obj.peek_name().startswith(f"{TARGET}_")
        ]
        if len(target_frames) != 19:
            raise RuntimeError(f"Expected 19 {TARGET} Sprite frames, found {len(target_frames)}")
        for frame_reader in target_frames:
            frame = frame_reader.read()
            tree = frame_reader.read_typetree()
            render_data = tree["m_RD"]
            rect = tree["m_Rect"]
            texture_rect = render_data["textureRect"]
            if (
                render_data["settingsRaw"] != 0
                or render_data["m_VertexData"]["m_VertexCount"] != 4
                or len(render_data["m_IndexBuffer"]) != 12
                or any(
                    abs(texture_rect[key] - rect[key]) > 0.001
                    for key in ("x", "y", "width", "height")
                )
                or frame.image.size != (round(rect["width"]), round(rect["height"]))
            ):
                raise RuntimeError(
                    f"{frame.m_Name} does not use verified full-rectangle render geometry"
                )

        illusts = UnityPy.load(io.BytesIO(archive.read(ILLUSTS_BUNDLE)))
        old_illust = _texture(illusts, SOURCE_ILLUST)
        old_illust_hash = hashlib.sha256(
            old_illust.image.convert("RGBA").tobytes()
        ).hexdigest()
        if old_illust_hash != original_illust_hash:
            raise RuntimeError("Original Unit_Illust_10570_02 texture changed")
        new_illust = _texture(sprites, TARGET_ILLUST)
        expected_illust = Image.open(ILLUST_IMAGE).convert("RGBA").resize(
            new_illust.image.size, Image.Resampling.LANCZOS
        )
        illust_difference = ImageChops.difference(
            new_illust.image.convert("RGBA"), expected_illust
        )
        illust_rms = max(ImageStat.Stat(illust_difference).rms)
        if illust_rms > 20:
            raise RuntimeError(
                f"Frieren portrait changed too much after bundle encoding: rms={illust_rms:.2f}"
            )
        source_illust_sprite = next(
            obj.read_typetree()
            for obj in illusts.objects
            if obj.type.name == "Sprite" and obj.read().m_Name == SOURCE_ILLUST
        )
        target_illust_sprite = next(
            obj.read_typetree()
            for obj in sprites.objects
            if obj.type.name == "Sprite" and obj.read().m_Name == TARGET_ILLUST
        )
        if (
            target_illust_sprite["m_RenderDataKey"][0]
            == source_illust_sprite["m_RenderDataKey"][0]
        ):
            raise RuntimeError("Frieren portrait still shares the source render GUID")
        target_illust_reader = next(
            obj
            for obj in sprites.objects
            if obj.type.name == "Sprite" and obj.peek_name() == TARGET_ILLUST
        )
        target_illust_render = target_illust_sprite["m_RD"]
        target_illust_rect = target_illust_sprite["m_Rect"]
        if (
            target_illust_render["texture"]["m_PathID"]
            != new_illust.object_reader.path_id
            or target_illust_render["settingsRaw"] != 0
            or target_illust_render["m_VertexData"]["m_VertexCount"] != 4
            or target_illust_reader.read().image.size
            != (
                round(target_illust_rect["width"]),
                round(target_illust_rect["height"]),
            )
        ):
            raise RuntimeError(
                "Frieren portrait does not use its cloned texture and full-rectangle mesh"
            )

        characters = UnityPy.load(io.BytesIO(archive.read(CHARACTERS_BUNDLE)))
        character_reader, character_bundle = _asset_bundle(characters)
        character_file = character_reader.assets_file
        prefab_names = {
            obj.read().m_Name
            for obj in characters.objects
            if obj.type.name == "GameObject"
        }
        if SOURCE not in prefab_names or TARGET not in prefab_names:
            raise RuntimeError("Original/new Farael prefabs are not both present")

        def dependency_ids(path: str, type_name: str) -> set[int]:
            info = _container_rows(character_bundle, path)[0][1]
            preloads = character_bundle.m_PreloadTable[
                info.preloadIndex : info.preloadIndex + info.preloadSize
            ]
            return {
                pointer.m_PathID
                for pointer in preloads
                if pointer.m_FileID == 0
                and pointer.m_PathID in character_file.objects
                and character_file.objects[pointer.m_PathID].type.name == type_name
            }

        for type_name, expected_count in (("AnimationClip", 10), ("AnimatorController", 1)):
            source_ids = dependency_ids(SOURCE_PREFAB_PATH, type_name)
            target_ids = dependency_ids(TARGET_PREFAB_PATH, type_name)
            if len(target_ids) != expected_count or source_ids & target_ids:
                raise RuntimeError(
                    f"{TARGET} {type_name} dependencies were not independently cloned"
                )

    print(f"Verified original sprite preserved; {TARGET} exact={sprite_exact}")
    print(f"Verified all 19 {TARGET} Sprites use 130x140 full-rectangle quads")
    print(
        f"Verified original portrait preserved; {TARGET_ILLUST} "
        f"encoding_rms={illust_rms:.2f}"
    )
    print(f"Verified {TARGET_ILLUST} uses a 1024x1024 full-rectangle Sprite")
    print("Verified Unit_10570_02 and Unit_10570_03 prefabs/controllers/clips coexist")
    print("Verified all five Unit_10570_03 Addressables locations")


def inject(apk: Path, xapk: Path, restore: bool = True) -> None:
    for image_path in (SPRITE_IMAGE, ILLUST_IMAGE):
        if not image_path.is_file():
            raise FileNotFoundError(image_path)
    if restore:
        _restore_pristine_base_assets(xapk, apk)

    with zipfile.ZipFile(apk) as archive:
        original_catalog = archive.read(CATALOG_PATH)
        sprites_raw = archive.read(SPRITES_BUNDLE)
        illusts_raw = archive.read(ILLUSTS_BUNDLE)
        characters_raw = archive.read(CHARACTERS_BUNDLE)

    pristine_illusts = UnityPy.load(io.BytesIO(illusts_raw))
    source_illust_texture = _texture(pristine_illusts, SOURCE_ILLUST)
    original_illust_hash = hashlib.sha256(
        source_illust_texture.image.convert("RGBA").tobytes()
    ).hexdigest()
    source_illust_tree = next(
        obj.read_typetree()
        for obj in pristine_illusts.objects
        if obj.type.name == "Sprite" and obj.peek_name() == SOURCE_ILLUST
    )

    print(f"Cloning {SOURCE} sprite sheet and 19 Sprite objects -> {TARGET}")
    sprites_new, sprite_paths, original_sprite_hash = _clone_texture_group(
        sprites_raw,
        source_path=SOURCE_SPRITE_PATH,
        target_path=TARGET_SPRITE_PATH,
        source_name=SOURCE,
        target_name=TARGET,
        replacement_path=SPRITE_IMAGE,
        namespace="sprites",
    )
    print(f"Cloning {TARGET_ILLUST} into the sprites bundle")
    sprites_new = _clone_illust_into_sprites_bundle(
        sprites_new,
        replacement_path=ILLUST_IMAGE,
        source_illust_tree=source_illust_tree,
    )
    print(f"Cloning {SOURCE} prefab hierarchy -> {TARGET}")
    characters_new, _ = _clone_prefab(characters_raw, sprite_paths=sprite_paths)
    print("Cloning source skin Addressables locations")
    catalog_new = _patch_catalog(original_catalog)

    _replace_zip_members(
        apk,
        {
            SPRITES_BUNDLE: sprites_new,
            CHARACTERS_BUNDLE: characters_new,
            CATALOG_PATH: catalog_new,
        },
    )
    _verify(apk, original_sprite_hash, original_illust_hash, sprite_paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK)
    parser.add_argument("--xapk", type=Path, default=DEFAULT_XAPK)
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="do not restore pristine base_assets.apk first (debug only)",
    )
    args = parser.parse_args()
    inject(args.apk.resolve(), args.xapk.resolve(), restore=not args.no_restore)


if __name__ == "__main__":
    main()
