#!/usr/bin/env bash
# Собирает архив для релиза: dist/salad-live-<версия>.tar.gz
set -euo pipefail
cd "$(dirname "$0")"
VER="$(python3 -c "import re;print(re.search(r\"__version__ = '([^']+)'\", open('src/salad-live.py').read())[1])")"
NAME="salad-live-$VER"
rm -rf dist && mkdir -p "dist/$NAME"
cp -r install.sh uninstall.sh README.md LICENSE src data extension docs "dist/$NAME/"
find "dist/$NAME" -name '__pycache__' -prune -exec rm -rf {} +
tar -C dist -czf "dist/$NAME.tar.gz" "$NAME"
rm -rf "dist/$NAME"
echo "dist/$NAME.tar.gz"
