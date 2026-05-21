# Crimson Save Editor

A PySide6 desktop tool for editing **Crimson Desert** save files. It handles inventory, equipment, quests, knowledge, abyss gates, dyes, and related save data.

## Install

1. Download the latest release build for your platform.
2. Place the app in a folder where you want it to keep config and backups.
3. Run it and let it auto-detect your save location, or point it at your save manually.

## Build from source

Linux:

```bash
./build-Nuitka.sh
./build-PyInstaller.sh
./build-linux.sh
```

Windows-native batch wrappers:

```bat
build-windows-nuitka.cmd
build-windows-pyinstaller.cmd
```

Linux-venv wrappers are also available for environments that launch the shell scripts through a virtualenv entry point:

```bat
build-linux-venv-nuitka.cmd
build-linux-venv-pyinstaller.cmd
```

## Notes

- The save editor shares parser/backend components with `CrimsonGameMods`.
- The Linux build expects the native backend artifacts to be present in the sibling `CrimsonGameMods` tree.
