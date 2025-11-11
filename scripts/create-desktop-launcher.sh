#!/bin/bash

# create-desktop-launcher.sh - Create a desktop launcher for the SOW/PO Manager UI

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DESKTOP_PATH="$HOME/Desktop"
APP_NAME="SOW-PO Manager.app"
APP_PATH="$DESKTOP_PATH/$APP_NAME"

echo "=========================================="
echo "Creating Desktop Launcher"
echo "=========================================="
echo ""
echo "This will create an app on your desktop that launches"
echo "the SOW/PO Manager UI with a double-click."
echo ""

# Create the .app bundle structure
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

# Create the executable script
cat > "$APP_PATH/Contents/MacOS/launcher" << 'EOF'
#!/bin/bash

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Open Terminal and run the launch script
osascript <<-APPLESCRIPT
    tell application "Terminal"
        activate
        do script "cd \"PROJECT_ROOT_PLACEHOLDER\" && ./scripts/launch-ui.sh"
    end tell
APPLESCRIPT
EOF

# Replace placeholder with actual project root
sed -i '' "s|PROJECT_ROOT_PLACEHOLDER|$PROJECT_ROOT|g" "$APP_PATH/Contents/MacOS/launcher"

# Make the launcher executable
chmod +x "$APP_PATH/Contents/MacOS/launcher"

# Create Info.plist
cat > "$APP_PATH/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIdentifier</key>
    <string>com.colibri.sow-po-manager</string>
    <key>CFBundleName</key>
    <string>SOW-PO Manager</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
</dict>
</plist>
EOF

# Create a simple icon (text file as placeholder)
cat > "$APP_PATH/Contents/Resources/applet.icns" << 'EOF'
This is a placeholder for an icon file.
You can replace this with a proper .icns file if you have one.
EOF

echo "✅ Desktop launcher created at:"
echo "   $APP_PATH"
echo ""
echo "You can now double-click 'SOW-PO Manager' on your desktop"
echo "to launch the application!"
echo ""
