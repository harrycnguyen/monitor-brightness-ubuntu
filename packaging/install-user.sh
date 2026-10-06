#!/bin/sh
# Install for the current user only (nothing is written outside $HOME):
#   - ~/.local/bin/monitor-brightness           launcher that runs this checkout
#   - an app-grid entry named "Monitor Brightness" with its icon (this is also what
#     GNOME shows in the top-left corner while the app runs, instead of the raw app id)
#   - with --autostart, start in the tray at login
# Undo with: packaging/install-user.sh --uninstall
set -e

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_ID=io.github.harrycnguyen.MonitorBrightness
BIN="$HOME/.local/bin/monitor-brightness"
APPS="$HOME/.local/share/applications/$APP_ID.desktop"
AUTOSTART="$HOME/.config/autostart/$APP_ID.desktop"
ICON="$HOME/.local/share/icons/hicolor/scalable/apps/$APP_ID.svg"

if [ "$1" = "--uninstall" ]; then
    rm -f "$BIN" "$APPS" "$AUTOSTART" "$ICON"
    echo "Removed."
    exit 0
fi

mkdir -p "$(dirname "$BIN")" "$(dirname "$APPS")" "$(dirname "$ICON")"
cp "$REPO/packaging/$APP_ID.svg" "$ICON"

cat > "$BIN" <<'LAUNCHER'
#!/bin/sh
# Right after being added to the i2c group, a session doesn't have it until the next
# login. Borrow it with sg so DDC works without logging out first.
if [ -z "$MONITOR_BRIGHTNESS_SG" ] \
    && ! id -nG | tr ' ' '\n' | grep -qx i2c \
    && getent group i2c | cut -d: -f4 | tr ',' '\n' | grep -qx "$(id -un)"; then
    export MONITOR_BRIGHTNESS_SG=1
    exec sg i2c -c "\"$0\" $*"
fi
exec env PYTHONPATH="@REPO@/src" python3 -m monitor_brightness "$@"
LAUNCHER
sed -i "s#@REPO@#$REPO#" "$BIN"
chmod +x "$BIN"

entry() {
    cat <<DESKTOP
[Desktop Entry]
Type=Application
Name=Monitor Brightness
Comment=Change the brightness of each monitor
Exec=$BIN gui $1
Icon=$APP_ID
Categories=Utility;Settings;
Terminal=false
DESKTOP
}

entry "" > "$APPS"
echo "Installed launcher: $BIN and the app-grid entry."

if [ "$1" = "--autostart" ]; then
    mkdir -p "$(dirname "$AUTOSTART")"
    entry "--background" > "$AUTOSTART"
    echo "Will start in the tray at login."
fi
