#!/bin/bash
set -e

echo "=========================================================="
echo " FinCom Books - macOS Native (.app & .dmg) Builder   "
echo "=========================================================="

APP_ROOT="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$APP_ROOT/dist_mac"
APP_BUNDLE="$DIST_DIR/FinComBooks.app"
CONTENTS="$APP_BUNDLE/Contents"
RESOURCES="$CONTENTS/Resources"
MACOS_BIN="$CONTENTS/MacOS"

# 1. Verification
echo "[1/4] Running core tests..."
python3 -m pytest tests/ -k "not browser and not presentation"

# 2. Compile Server Binary (Zero .py Leakage)
echo "[2/4] Compiling native Mach-O binary with Nuitka..."
rm -rf "$DIST_DIR"
mkdir -p "$MACOS_BIN" "$RESOURCES"

python3 -m nuitka \
    --standalone \
    --output-dir="$DIST_DIR/build" \
    --output-filename=app_server \
    app_server.py

# Move compiled binaries to App Bundle
cp -R "$DIST_DIR/build/app_server.dist/"* "$MACOS_BIN/"
rm -rf "$DIST_DIR/build"

# 3. Bundle Assets & Launcher
echo "[3/4] Packaging frontend assets, icon, and launcher..."
# The server serves files from its own folder, so the frontend sits next to app_server, not in Resources.
cp index.html fidelity.css theme.css workflows.js fincom_screens.js voucher_logic.js lookup_context.js print_view.js date_picker.js "$MACOS_BIN/"
cp logo.png favicon.ico manifest.json version.json LICENSE "$MACOS_BIN/"
if [ -f "app.icns" ]; then
    cp app.icns "$RESOURCES/app.icns"
fi

# Copy Launcher as primary executable
cp "$APP_ROOT/launch_mac.sh" "$MACOS_BIN/FinComBooks"
chmod +x "$MACOS_BIN/FinComBooks"
chmod +x "$MACOS_BIN/app_server"

# Generate Info.plist
cat <<EOF > "$CONTENTS/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>FinComBooks</string>
    <key>CFBundleIconFile</key>
    <string>app.icns</string>
    <key>CFBundleIdentifier</key>
    <string>com.fincomindia.books</string>
    <key>CFBundleName</key>
    <string>FinCom Books</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 4. Generate Distributable DMG
# Ad-hoc sign so Apple Silicon shows "unidentified developer" (fixable with Open) instead of "damaged".
codesign --force --deep --sign - "$APP_BUNDLE"

echo "[4/4] Creating FinComBooks.dmg..."
DMG_FILE="$DIST_DIR/FinComBooksSetup.dmg"
rm -f "$DMG_FILE"

DMG_STAGE="$DIST_DIR/dmg_stage"
mkdir -p "$DMG_STAGE"
cp -R "$APP_BUNDLE" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"

hdiutil create \
    -volname "FinCom Books" \
    -srcfolder "$DMG_STAGE" \
    -ov -format UDZO \
    "$DMG_FILE"

rm -rf "$DMG_STAGE"
echo "=========================================================="
echo " [SUCCESS] Created: $DMG_FILE"
echo " Drag 'FinComBooks.app' to /Applications to install."
echo "=========================================================="
