# Field JSON v3.1 — Multi-Target Field Patching Specification

**Version**: 3.1
**Codename**: Multi-Target Field Patching
**Author**: NattKh / RicePaddySoftware (CrimsonGameMods)
**Co-author**: exodiaprivate-eng (dmm-parser parser dispatch)
**Date**: 2026-05-01
**Status**: Stable — implemented in CrimsonGameMods Stacker v1.1.5 + DMM 1.3.4+
**License**: Mozilla Public License 2.0 — see LICENSE
**Supersedes**: FIELD_JSON_V3_SPEC.md (v3.0 single-target)

---

## Copyright Notice

```
Copyright (c) 2026 RicePaddySoftware. All rights reserved.

This specification ("Field JSON v3.1 — Multi-Target Field Patching") and
all associated reference implementations are licensed under the Mozilla
Public License 2.0. The "Field JSON v3.1", "Multi-Target Field Patching",
and associated wordmarks are trademarks of RicePaddySoftware as used in
the context of Crimson Desert mod tooling.

Implementations targeting Crimson Desert game data must preserve this
notice and the MPL 2.0 license text in any redistribution.
```

---

## Why v3.1 exists

Field JSON v3.0 (FIELD_JSON_V3_SPEC.md) introduced **field-name-based** edits
that survive game updates by resolving against the current `iteminfo.pabgb`
at apply-time. It works perfectly for items, but had two limitations:

1. **Single-target document** — `target` was a top-level string locked to
   `iteminfo.pabgb`. Mods touching multiple tables (item + gimmick + skill)
   couldn't be expressed in one document.
2. **Limited table coverage** — only `iteminfo` had a typed parser exposed
   to the apply layer. Mods touching `gimmick_info`, `condition_info`,
   `drop_set_info`, `buff_info`, `character_info`, etc. fell back to
   byte-level mods and broke on every game update.

v3.1 closes both gaps by introducing **multi-target intent grouping** and
the **typed-table dispatcher** (`dmm_parser.parse_table`) that exposes
122 typed tables uniformly.

---

## Detection

A document is Field JSON v3.1 if and only if:

```
doc["format"] == 3
AND
doc["targets"] is a non-empty list
```

A document is v3.0 (legacy single-target) if and only if:

```
doc["format"] == 3
AND
doc["intents"] is a non-empty list
AND
"targets" is absent
```

A v3.1-aware loader **must** handle both shapes. A v3.0-only loader
should skip the document or apply only the iteminfo subset (see
"Backward compatibility" below).

---

## File structure

```json
{
  "modinfo": {
    "title": "QoL: Faster Cooldowns + Stronger Boss Drops",
    "version": "1.0",
    "author": "ExampleAuthor",
    "description": "12 field-level intent(s) across 3 target(s) — 5 iteminfo, 4 gimmick_info, 3 drop_set_info",
    "note": "Format 3.1 multi-target — uses field names, survives game updates. Requires DMM 1.3.4+ for non-iteminfo targets."
  },
  "format": 3,
  "format_minor": 1,
  "targets": [
    {
      "file": "iteminfo.pabgb",
      "intents": [
        { "entry": "Oath_Of_Darkness", "key": 391518535, "field": "cooltime", "op": "set", "new": 1 }
      ]
    },
    {
      "file": "gimmick_info.pabgb",
      "intents": [
        { "entry": "Sword_Aura_FX", "key": 70001, "field": "duration_ms", "op": "set", "new": 5000 }
      ]
    },
    {
      "file": "drop_set_info.pabgb",
      "intents": [
        { "entry": "DropSet_FinalBoss", "key": 99999, "field": "drop_count_max", "op": "set", "new": 10 }
      ]
    }
  ]
}
```

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `format` | `int` | yes | Always `3`. |
| `format_minor` | `int` | recommended | `1` for v3.1 documents. Absent or `0` = v3.0. |
| `targets` | `list[target]` | yes (v3.1) | Non-empty array of target sections. |
| `modinfo` | `object` | yes | Same shape as v3.0. |

### Target section

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | `string` | yes | The pabgb filename (without path). E.g. `"iteminfo.pabgb"`, `"gimmick_info.pabgb"`. |
| `intents` | `list[intent]` | yes | Non-empty list of intents to apply to this file. |

### Intent (unchanged from v3.0)

| Field | Type | Required | Description |
|---|---|---|---|
| `entry` | `string` | yes | The record's `string_key`. **Primary lookup key.** May be empty if the table has no string_key. |
| `key` | `int` | yes | The record's numeric key. Fallback when `entry` doesn't match. |
| `field` | `string` | yes | Dot-separated field path (see "Field path syntax"). |
| `op` | `"set"` | yes | Currently only `set` is supported. v3.2 will introduce `list_set` / `list_append` / `list_remove` / `list_merge`. |
| `new` | `any` | yes | New value. Type must match the parser's typed schema. |

---

## Supported targets

A v3.1 loader **must** dispatch on `target.file` to the correct parser. The
reference implementation (`dmm_parser.parse_table`) supports 122 tables.
Each `target.file` is converted to a snake_case table name by stripping
`.pabgb`:

| `target.file` | `dmm_parser` table_name |
|---|---|
| `iteminfo.pabgb` | (handled inline by ItemBuffs/legacy v3.0 path) |
| `equipslotinfo.pabgb` | `equip_slot_info` |
| `skill.pabgb` | `skill_info` |
| `gimmick_info.pabgb` | `gimmick_info` |
| `condition_info.pabgb` | `condition_info` |
| `buff_info.pabgb` | `buff_info` |
| `drop_set_info.pabgb` | `drop_set_info` |
| `character_info.pabgb` | `character_info` |
| `effect_info.pabgb` | `effect_info` |
| `interaction_info.pabgb` | `interaction_info` |
| ... | ... 110 more — see `dmm_parser.parse_table` docs |

A loader receiving an unknown `target.file` **must** skip that target
section (warn but don't fail the document).

### Localization target — `paloc.pamt`

Paloc records have a different identity scheme from PABGB tables (no u32
record key — records are addressed by the tuple `(category u8, key string)`).
A v3.1 loader **must** map intent fields as follows for `target.file ==
"paloc.pamt"`:

| Intent field | Paloc semantics |
|---|---|
| `entry` | Paloc record's `key` string (e.g. `"4290772592"`) |
| `key` | Category byte: `0x70` for item names, `0x71` for descriptions, `0x07` for items, `0x03` for characters, `0x2F` for UI text |
| `field` | Always `"value"` — the only patchable field |
| `new` | New localized text (UTF-8 string) |

Example — set the name and description for a custom item under key `999001`:

```json
{
  "target": { "file": "paloc.pamt" },
  "intents": [
    { "entry": "4290772592", "key": 112, "field": "value", "new": "Custom Sword" },
    { "entry": "4290772593", "key": 113, "field": "value", "new": "Hits like a truck." }
  ]
}
```

Where `4290772592 = (999001 << 32) | 0x70` (name lookup) and `4290772593 = (999001 << 32) | 0x71` (description lookup). `key` values `112` and `113` are decimal `0x70` and `0x71`.

---

## Asset target type (v3.1, additive)

In addition to the field-level intent shape above, v3.1 supports a
**binary asset target type** for textures, audio, and other binary files
that the game expects in their original on-disk format. Use this when the
data isn't a typed PABGB table (DDS textures, WEM/BNK audio, ReShade
configs, etc.).

### Schema

```json
{
  "target": { "file": "0009/character/texture/macduff/diffuse.dds" },
  "type": "asset",
  "source": "assets/macduff_diffuse.dds",
  "sha256": "abc123..."
}
```

### Field reference

| Field | Required | Type | Description |
|---|---|---|---|
| `target.file` | yes | string | The vpath inside the game's archive structure. First path segment **should** be a 4-digit PAZ group prefix (`0009/`, `0012/`, `0014/`, etc.) for unambiguous routing. |
| `type` | yes | string | Must be exactly `"asset"`. (Field-level targets omit this; loaders treat absent `type` as field-level for backward compat with v3.0/v3.1 base.) |
| `source` | yes | string | Path to the binary file, **relative to the `.field.json` location**. Convention: place assets under an `assets/` subfolder. Forward or back slashes accepted; loaders normalize. |
| `sha256` | optional | string | Hex SHA-256 of the source file. When present, loaders **must** verify and reject the mod if the hash mismatches. Helps detect accidentally truncated mods or asset swap during distribution. |

### Path resolution

`source` is resolved relative to the directory containing the
`.field.json` file. Absolute paths and `..` segments are **not allowed**
(reject the mod with a clear error). This keeps mods self-contained and
prevents path-traversal exploits.

```
mymod/
├── mymod.field.json          ← references assets/...
└── assets/
    ├── textures/
    │   └── macduff_diffuse.dds
    └── audio/
        └── voice_attack01.wem
```

### File-extension dispatch

The vpath's file extension determines which game subsystem the asset
plugs into. Loaders **must** route as follows:

| Extension | Asset class | Notes |
|---|---|---|
| `.dds` | Texture | DXT1/DXT5 → standard injection. DX10/BC7 → requires PATHC entry registration with template index. |
| `.wem` | Wwise audio (event-driven) | Direct PAZ injection — Wwise reads from base PAZ groups, not overlay. |
| `.bnk` | Wwise SoundBank | Same as `.wem` — direct PAZ injection in the WEM's native group. |
| `.ttf` / `.otf` | Font | Standard PAZ overlay (legacy compatible). |
| `.fx` / `.fxh` / `.ini` | ReShade preset / shader / config | Text file replacement, typically in the game-root directory. |
| (unknown) | Unsupported | Loader **must** skip and emit a warning. |

### Mixed mods

A single `.field.json` MAY contain field-level targets, the `paloc.pamt`
target, and asset-type targets in any combination — they all live in the
same `targets` array. This is the recommended way to ship a complete
"reskin + buff" mod as a single file plus an `assets/` folder.

```json
{
  "format": 3,
  "format_minor": 1,
  "modinfo": { "title": "Macduff Overhaul", "version": "1.0" },
  "targets": [
    {
      "target": { "file": "iteminfo.pabgb" },
      "intents": [
        { "entry": "Macduff_Sword", "field": "damage", "new": 999000 }
      ]
    },
    {
      "target": { "file": "paloc.pamt" },
      "intents": [
        { "entry": "4290772592", "key": 112, "field": "value", "new": "999K Sword" }
      ]
    },
    {
      "target": { "file": "0009/character/texture/macduff/diffuse.dds" },
      "type": "asset",
      "source": "assets/macduff_diffuse.dds",
      "sha256": "abc123..."
    }
  ]
}
```

### Validation requirements

A v3.1 loader **must**:

1. Resolve `source` paths and reject absolute paths or paths containing `..`.
2. Read the asset file and fail loudly if missing.
3. If `sha256` is present, verify and reject on mismatch.
4. Validate the asset against its expected format using `dmm_parser` helpers (`classify_dds`, `classify_wem`, `parse_bnk`) when available.
5. Skip with a warning — not fatal — when the file extension is not in the dispatch table.

---

## Field path syntax

Identical to v3.0 with one addition: nested-list element fields.

| Path | Meaning |
|---|---|
| `cooltime` | top-level field |
| `drop_default_data.use_socket` | nested dict |
| `enchant_data_list[3].level` | element 3 of list, then field `level` |
| `enchant_data_list[3].equip_buffs[0].buff` | nested deep |
| `tags` | replace whole list of primitives |

### Path resolution algorithm (Python reference)

```python
import re

_BRACKET_RE = re.compile(r'^(.+?)\[(\d+)\]$')

def apply_field_set(target: dict, field_path: str, value):
    parts = re.split(r'\.(?![^\[]*\])', field_path)
    obj = target
    for part in parts[:-1]:
        m = _BRACKET_RE.match(part)
        if m:
            key, idx = m.group(1), int(m.group(2))
            obj = obj[key][idx]
        else:
            obj = obj[part]
    last = parts[-1]
    m = _BRACKET_RE.match(last)
    if m:
        key, idx = m.group(1), int(m.group(2))
        obj[key][idx] = value
    else:
        obj[last] = value
```

---

## Apply algorithm (v3.1 loader)

```python
import dmm_parser

def apply_v3_1(doc: dict, game_dir: str, output_overlay_dir: str):
    if doc.get("format") != 3:
        raise ValueError("not a Field JSON v3 document")

    targets = doc.get("targets")
    if not targets:
        # v3.0 fallback
        targets = [{"file": doc.get("target", "iteminfo.pabgb"),
                    "intents": doc.get("intents", [])}]

    for tgt in targets:
        file_name = tgt["file"]
        intents   = tgt["intents"]
        table_name = file_name[:-len(".pabgb")] if file_name.endswith(".pabgb") else file_name

        # Extract vanilla bytes from PAZ
        pabgb = dmm_parser.extract_file(game_dir, "0008", "gamedata/binary__/client/bin", file_name)
        pabgh = dmm_parser.extract_file(game_dir, "0008", "gamedata/binary__/client/bin",
                                         file_name[:-len(".pabgb")] + ".pabgh")

        # Parse to typed records
        try:
            items = dmm_parser.parse_table(table_name, pabgb, pabgh)
        except ValueError:
            print(f"SKIP target {file_name}: dmm_parser doesn't know this table")
            continue

        # Index for lookup
        items_by_name = {it.get("string_key", ""): it for it in items}
        items_by_key  = {it.get("key", -1): it for it in items}

        # Apply each intent
        for intent in intents:
            target = items_by_name.get(intent["entry"])
            if not target:
                target = items_by_key.get(intent.get("key"))
            if not target:
                print(f"SKIP intent: entry '{intent['entry']}' not found")
                continue
            if intent.get("op") == "set":
                apply_field_set(target, intent["field"], intent["new"])

        # Serialize back and write to overlay
        modified = dmm_parser.serialize_table(table_name, items)
        out_path = os.path.join(output_overlay_dir,
            "gamedata/binary__/client/bin", file_name)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(modified)
```

---

## Backward compatibility

**v3.0 documents apply unchanged in v3.1 loaders** — the absence of `targets`
triggers the legacy single-target path.

**v3.1 documents in v3.0 loaders** — v3.0 loaders see `format == 3` but
`intents` absent. They **should** treat as unsupported and warn, NOT fail.
Recommended fallback for v3.0 loaders that want partial support: extract
the `iteminfo.pabgb` target's intents and apply them, ignoring all other
targets. The CrimsonGameMods Stacker emits v3.1 docs with this fallback
behavior in mind.

---

## Mod stacking semantics

Two v3.1 mods stack cleanly when:
- They target **different files**, OR
- They target the **same file** but **different entries**, OR
- They target the **same file**, **same entry**, but **different fields**.

When two mods target the **same file, same entry, same field** with
different `new` values, the loader **must** choose one (last-loaded wins
by default) and surface the conflict to the user. The CrimsonGameMods
Stacker UI shows these in a per-field conflict table.

---

## Validation

After applying intents, validate with a roundtrip check:

```python
for table in modified_tables:
    rt = dmm_parser.serialize_table(table_name, items)
    parsed_again = dmm_parser.parse_table(table_name, rt, pabgh)
    # If any item mismatches, revert that item to vanilla
```

This catches structural corruption (wrong list lengths, missing required
fields) before the mod reaches the game.

---

## Trademarks and licensing

"Field JSON v3", "Field JSON v3.1", and "Multi-Target Field Patching" are
unregistered marks of RicePaddySoftware as used in the Crimson Desert
modding ecosystem. Use of these terms in compatible loaders/exporters is
permitted under MPL 2.0 provided this notice is preserved.

---

## Future work (v3.2 preview, NOT in v3.1)

These are documented for visibility but **must not** appear in v3.1 docs:

- **List operations**: `list_set` / `list_append` / `list_remove` /
  `list_merge` ops alongside `set`.
- **Cross-table references**: `"new": "@gimmick_info.Sword_Aura_FX"` resolves
  to the runtime key at apply time.
- **Conditional intents**: `"if": { "field": "level", ">=": 50 }` gates
  intents on entry properties.
- **Schema discovery API**: `dmm_parser.describe_table(name)` returns the
  field schema for tooling/UI.

A v3.2 document **must** still satisfy `format == 3` for v3.0/v3.1 loader
detection; the new ops will be additive within the existing intent shape.

---

## Reference implementations

| Component | Repo / file | Status |
|---|---|---|
| Parser dispatcher (Rust → Python) | `dmm-parser` `src/python.rs` `parse_table` | ✅ Shipped (commit `f054b5e`) |
| Stacker exporter (multi-target) | `CrimsonGameMods` `gui/tabs/stacker.py` `_export_field_json` | ✅ Shipped (PR #49) |
| Stacker field-level catchall | `CrimsonGameMods` `gui/tabs/stacker.py` `_diff_table_field_level` | ✅ PR #53 |
| DMM v3.1 apply | `DMMLoader` (Tauri/Rust) | ⏳ Pending — see `apply_v3_1` algorithm above |

---

## Questions / Support

- **Format spec**: NattKh / RicePaddySoftware (CrimsonGameMods Discord)
- **dmm-parser API**: exodiaprivate-eng (dmm-parser GitHub Issues)
- **DMM apply layer**: NattKh / RicePaddySoftware
