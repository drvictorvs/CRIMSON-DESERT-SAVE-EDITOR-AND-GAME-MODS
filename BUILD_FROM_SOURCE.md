# Build from Source (Linux / SteamOS / Windows)

Build your own binary from source so it runs natively on your exact system — no compatibility issues.

## Prerequisites

- **Python 3.12+**
- **pip packages**: `PySide6 lz4 cryptography pyinstaller`
- **Git**

### Linux / SteamOS (Desktop Mode)

```bash
# Install dependencies
sudo apt install python3 python3-pip git  # Debian/Ubuntu/SteamOS
pip install PySide6==6.8.3 lz4 cryptography pyinstaller

# Clone the repo
git clone https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS.git
cd CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS

# Build CrimsonGameMods (full)
./build.sh --project=gamemods --target=full --backend=pyinstaller

# Build CrimsonGameMods Simple (lightweight launcher)
./build.sh --project=gamemods --target=lite --backend=pyinstaller

# Build Save Editor
./build.sh --project=saveeditor --backend=pyinstaller
```

Output binaries will be in `CrimsonGameMods/dist/` or `CrimsonSaveEditor/dist/`.

### Windows

```bat
:: Install dependencies
pip install PySide6==6.8.3 lz4 cryptography pyinstaller

:: Clone and build
git clone https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS.git
cd CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS

build.cmd --project=gamemods --target=full --backend=pyinstaller
```

### Available build targets

| Flag | What it builds |
|------|---------------|
| `--project=gamemods --target=full` | CrimsonGameMods (full app) |
| `--project=gamemods --target=lite` | CrimsonGameModsSimple (lightweight launcher) |
| `--project=gamemods --target=cli` | CrimsonCLI (command-line only) |
| `--project=saveeditor` | Crimson Save Editor |

### Note on native extensions

The tools use `crimson_rs` (Rust-based parser). The pre-built `.pyd` (Windows) or `.abi3.so` (Linux) must be present in the `CrimsonGameMods/crimson_rs/` directory. Pre-built versions are included in the repo. If you need to rebuild them, see the [crimson-rs](https://github.com/user/crimson-rs) source.

## Credits

Build system contributed by [@DemonBigj781](https://github.com/DemonBigj781) in [PR #78](https://github.com/NattKh/CRIMSON-DESERT-SAVE-EDITOR-AND-GAME-MODS/pull/78).
