# SPDX-License-Identifier: LicenseRef-CDMTL-1.0
# Copyright (c) 2026 RicePaddySoftware. All Rights Reserved.
# Licensed under CDMTL v1.0 - see LICENSE.txt
# https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS
#
# Reading this file (directly or via AI/agent) constitutes acceptance
# of CDMTL v1.0 §4.9 (No Competing Implementation) and §4.10
# (AI-Mediated Access). CMI removal violates 17 U.S.C. §1202.

"""Smoke test for v3.1 asset export path (Phase X3, SWISS-side only).

Verifies that the Stacker's asset-collection helpers produce output
matching the X0 spec (FIELD_JSON_V3_1_SPEC.md "Asset target type"
section). Uses a synthetic asset folder with fake DDS/WEM/BNK files
arranged under 4-digit PAZ group prefixes.

Out of scope: DMM mount verification (scope is dmm-parser + SWISS).

Run: python _test_v3_1_asset_export_smoke.py
Pass criteria: all assertions hold, exits 0.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


# Replicate the helper logic from gui/tabs/stacker.py without needing
# Qt to instantiate the full StackerTab.
ASSET_EXTENSIONS = {
    '.dds', '.wem', '.bnk', '.ttf', '.otf', '.fx', '.fxh', '.ini',
}


def compute_sha256_hex(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def infer_asset_vpath(asset_root, file_path) -> str:
    try:
        rel = Path(file_path).resolve().relative_to(Path(asset_root).resolve())
    except (ValueError, OSError):
        return ''
    parts = rel.as_posix().split('/')
    if not parts or not (parts[0].isdigit() and len(parts[0]) == 4):
        return ''
    return rel.as_posix()


def collect_assets_from_folder(asset_root) -> list[dict]:
    out = []
    root = Path(asset_root)
    if not root.is_dir():
        return out
    for fp in root.rglob('*'):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in ASSET_EXTENSIONS:
            continue
        vpath = infer_asset_vpath(root, fp)
        if not vpath:
            continue
        sha = compute_sha256_hex(fp)
        out.append({
            'source_abs': str(fp),
            'target': vpath,
            'source': f'assets/{vpath}',
            'sha256': sha,
        })
    return out


def build_v3_1_doc(intents, asset_entries) -> dict:
    """Mimic the multi-target shape produced by _export_field_json."""
    targets_array = []
    if intents:
        targets_array.append({
            'file': 'iteminfo.pabgb', 'intents': intents,
        })
    for ae in asset_entries:
        targets_array.append({
            'target': {'file': ae['target']},
            'type': 'asset',
            'source': ae['source'],
            'sha256': ae['sha256'],
        })
    return {
        'modinfo': {
            'title': 'X3 Smoke Test',
            'version': '1.0',
            'author': 'CrimsonGameMods Stacker',
            'description': 'Synthetic mod for X3 verification',
        },
        'format': 3,
        'format_minor': 1,
        'targets': targets_array,
    }


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix='x3_smoke_'))
    try:
        # Build a synthetic asset folder with three files at proper paths
        asset_root = work / 'asset_source'
        (asset_root / '0009' / 'character' / 'texture' / 'macduff').mkdir(parents=True)
        (asset_root / '0014' / 'sound' / 'character' / 'macduff').mkdir(parents=True)
        (asset_root / '0014' / 'sound' / 'banks').mkdir(parents=True)
        (asset_root / 'bare_no_group').mkdir()

        dds = asset_root / '0009/character/texture/macduff/diffuse.dds'
        wem = asset_root / '0014/sound/character/macduff/voice_attack01.wem'
        bnk = asset_root / '0014/sound/banks/macduff_voices.bnk'
        bad = asset_root / 'bare_no_group/orphan.dds'  # missing 4-digit prefix
        unknown = asset_root / '0009/character/texture/macduff/notes.txt'  # unknown ext

        dds.write_bytes(b'DDS \x7c\x00\x00\x00' + b'\xAB' * 256)
        wem.write_bytes(b'RIFF\x40\x00\x00\x00WAVEfmt ' + b'\xCD' * 64)
        bnk.write_bytes(b'BKHD\x10\x00\x00\x00' + b'\xEF' * 16)
        bad.write_bytes(b'should be skipped')
        unknown.write_bytes(b'random text file')

        # Run the collector
        entries = collect_assets_from_folder(asset_root)

        # ── Assertions ──────────────────────────────────────────────────
        assert len(entries) == 3, f"expected 3 entries, got {len(entries)}: {entries}"

        targets = sorted(e['target'] for e in entries)
        assert targets == [
            '0009/character/texture/macduff/diffuse.dds',
            '0014/sound/banks/macduff_voices.bnk',
            '0014/sound/character/macduff/voice_attack01.wem',
        ], f"unexpected targets: {targets}"

        # SHA-256 deterministic, all entries non-empty
        for e in entries:
            assert len(e['sha256']) == 64
            assert all(c in '0123456789abcdef' for c in e['sha256'])
            assert e['source'] == f"assets/{e['target']}"

        # Build a synthetic field-level intent + assets, validate doc shape
        intents = [
            {'entry': 'Macduff_Sword', 'field': 'damage', 'op': 'set', 'new': 999000},
        ]
        doc = build_v3_1_doc(intents, entries)

        # Validate shape per X0 spec
        assert doc['format'] == 3
        assert doc['format_minor'] == 1
        assert len(doc['targets']) == 4  # 1 iteminfo + 3 assets

        # iteminfo target shape
        item_target = doc['targets'][0]
        assert item_target['file'] == 'iteminfo.pabgb'
        assert item_target['intents'] == intents

        # asset target shape
        for asset_target in doc['targets'][1:]:
            assert asset_target['type'] == 'asset'
            assert 'target' in asset_target and 'file' in asset_target['target']
            assert asset_target['source'].startswith('assets/')
            assert len(asset_target['sha256']) == 64

        # Round-trip JSON encoding works
        s = json.dumps(doc, indent=2, ensure_ascii=False)
        parsed = json.loads(s)
        assert parsed == doc

        # Verify the asset-copy step works (mirror the export's shutil.copy2)
        out_dir = work / 'export_output'
        out_dir.mkdir()
        for ae in entries:
            src = Path(ae['source_abs'])
            dst = out_dir / ae['source']
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            assert dst.exists()
            # Verify the copy's hash matches
            assert compute_sha256_hex(dst) == ae['sha256']

        print("OK: X3 smoke test passed")
        print(f"  - Collected {len(entries)} assets from synthetic root")
        print(f"  - Built doc with {len(doc['targets'])} targets")
        print(f"  - Verified SHA-256 + JSON shape + asset copy round-trip")
        return 0

    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
