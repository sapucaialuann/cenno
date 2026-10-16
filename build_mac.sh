#!/bin/bash
# Builds dist/newMotion.app and dist/newMotion-<version>.dmg on an Apple Silicon Mac.
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(grep -E '^VERSION = ' newMotion.spec | cut -d'"' -f2)
VENV=.venv-build

if [ ! -x "$VENV/bin/python" ]; then
  /usr/bin/python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
fi
"$VENV/bin/pip" install -q -r requirements-build.txt

echo "== icon"
rm -rf build/icon.iconset && mkdir -p build/icon.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s assets/icon_1024.png --out build/icon.iconset/icon_${s}x${s}.png >/dev/null
  d=$((s * 2))
  sips -z $d $d assets/icon_1024.png --out build/icon.iconset/icon_${s}x${s}@2x.png >/dev/null
done
iconutil -c icns build/icon.iconset -o build/newMotion.icns

echo "== app"
"$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN newMotion.spec
codesign --force --deep --sign - dist/newMotion.app
codesign --verify --deep dist/newMotion.app && echo "signature ok (ad-hoc)"

echo "== dmg"
rm -rf build/dmg && mkdir -p build/dmg
cp -R dist/newMotion.app build/dmg/
ln -s /Applications build/dmg/Applications
rm -f "dist/newMotion-$VERSION.dmg"
hdiutil create -quiet -volname "newMotion" -srcfolder build/dmg -ov -format UDZO "dist/newMotion-$VERSION.dmg"
du -sh dist/newMotion.app "dist/newMotion-$VERSION.dmg"
echo BUILD_OK
