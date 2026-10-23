#!/bin/bash
# Builds dist/Cenno.app and dist/Cenno-<version>.dmg on an Apple Silicon Mac.
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(grep -E '^VERSION = ' Cenno.spec | cut -d'"' -f2)
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
iconutil -c icns build/icon.iconset -o build/Cenno.icns

echo "== app"
"$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN Cenno.spec

echo "== layered icon (Dark, Clear, Tinted)"
# Needs Xcode 26 (not just the Command Line Tools). Falls back to the flat icon.
XCODE_DEV=/Applications/Xcode.app/Contents/Developer
if [ -x "$XCODE_DEV/usr/bin/actool" ]; then
  rm -rf build/assets && mkdir -p build/assets
  DEVELOPER_DIR="$XCODE_DEV" xcrun actool assets/Cenno.icon \
    --compile build/assets --app-icon Cenno --platform macosx \
    --minimum-deployment-target 12.0 --include-all-app-icons \
    --output-partial-info-plist build/assets/partial.plist >/dev/null
  cp build/assets/Assets.car dist/Cenno.app/Contents/Resources/
  /usr/libexec/PlistBuddy -c "Add :CFBundleIconName string Cenno" dist/Cenno.app/Contents/Info.plist 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :CFBundleIconName Cenno" dist/Cenno.app/Contents/Info.plist
else
  echo "Xcode not found, using the flat icon only"
fi
codesign --force --deep --sign - dist/Cenno.app
codesign --verify --deep dist/Cenno.app && echo "signature ok (ad-hoc)"

echo "== dmg"
rm -rf build/dmg && mkdir -p build/dmg
cp -R dist/Cenno.app build/dmg/
ln -s /Applications build/dmg/Applications
rm -f "dist/Cenno-$VERSION.dmg"
hdiutil create -quiet -volname "Cenno" -srcfolder build/dmg -ov -format UDZO "dist/Cenno-$VERSION.dmg"
du -sh dist/Cenno.app "dist/Cenno-$VERSION.dmg"
echo BUILD_OK
