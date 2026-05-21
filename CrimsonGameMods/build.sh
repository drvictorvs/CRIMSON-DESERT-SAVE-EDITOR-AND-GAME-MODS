#!/usr/bin/env bash
set -euo pipefail

target=full
backend=nuitka

for arg in "$@"; do
  case "$arg" in
    --target=*) target="${arg#*=}" ;;
    --backend=*) backend="${arg#*=}" ;;
    -h|--help)
      cat <<'USAGE'
Usage: build.sh [--target=cli|full|lite] [--backend=nuitka|pyinstaller]
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

case "$target" in
  cli|full|lite) ;;
  *) echo "Invalid target: $target" >&2; exit 1 ;;
esac

case "$backend" in
  nuitka|pyinstaller) ;;
  *) echo "Invalid backend: $backend" >&2; exit 1 ;;
esac

script_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$script_dir"

if [[ "$backend" == "nuitka" ]]; then
  exec "$script_dir/build-${target}-Nuitka.sh"
fi

exec "$script_dir/build-${target}-PyInstaller.sh"
