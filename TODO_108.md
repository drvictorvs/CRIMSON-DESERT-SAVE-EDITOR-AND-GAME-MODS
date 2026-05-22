# 1.0.8 TODO

## Optional UI Enhancements

- [ ] Expose `is_extract_able_item` (new u8 field) as an editable toggle in the ItemBuffs tab
- [ ] Show tool slot info for equippable tools (logging axe, mallet, shovel, broom, scythe, pickaxe, drill, fan)
- [ ] Consider showing the new `unk_docking_108` field in DockingChildData if its purpose becomes clear

## Parser Status (COMPLETE)

- All 122 pabgb tables roundtrip on 1.0.8
- ItemInfo 6314/6314 (100%) typed roundtrip
- Updated .pyd deployed to CrimsonGameMods_Clean
- No code changes needed in the tool itself — parser update was sufficient
