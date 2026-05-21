#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "Clearing caches..."
find . -type d -name '__pycache__' -prune -exec rm -rf '{}' +
rm -rf dist

echo "Building with PyInstaller..."

python -m PyInstaller CrimsonGameMods.spec --noconfirm

echo
echo "Done. Output: dist/CrimsonGameMods"
