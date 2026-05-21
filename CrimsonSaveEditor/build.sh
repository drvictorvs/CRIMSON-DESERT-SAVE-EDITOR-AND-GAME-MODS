#!/usr/bin/env bash
set -euo pipefail

backend=nuitka

for arg in "$@"; do
  case "$arg" in
    --backend=*) backend="${arg#*=}" ;;
    -h|--help)
      cat <<'USAGE'
Usage: build.sh [--backend=nuitka|pyinstaller]
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

case "$backend" in
  nuitka|pyinstaller) ;;
  *) echo "Invalid backend: $backend" >&2; exit 1 ;;
esac

script_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

if [[ "$backend" == "nuitka" ]]; then
  exec "$script_dir/build-Nuitka.sh"
fi

exec "$script_dir/build-PyInstaller.sh"
