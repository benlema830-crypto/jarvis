#!/usr/bin/env bash
# Set up this Fedora laptop for Jarvis: his dashboard and a room microphone, both talking to the PC over Tailscale.
# Run:  curl -fsSL __JARVIS_URL__/laptop | bash
# and type the 6-digit code from the PC (tray icon > "Set up the laptop"). Nothing here needs root except
# installing an audio recorder if the laptop has none. Run it again any time to update or re-pair.
set -euo pipefail

URL="__JARVIS_URL__"
HOME_DIR="$HOME/.local/share/jarvis-laptop"
CONF_DIR="$HOME/.config/jarvis-laptop"
BIN="$HOME/.local/bin"

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }

say "Jarvis laptop setup"
if ! curl -fsS --max-time 10 -o /dev/null "$URL/login"; then
  echo "Can't reach Jarvis at $URL. Turn Tailscale on (sudo tailscale up), make sure the PC is awake, and try again."
  exit 1
fi

if [ -f "$CONF_DIR/config.json" ] && [ "${1:-}" != "--pair" ]; then
  echo "Already paired; updating the programs. (Run with --pair to pair again.)"
else
  read -rp "Pairing code shown on the PC: " CODE < /dev/tty
  KEY=$(curl -fsS -X POST -H 'Content-Type: application/json' -d "{\"code\": \"${CODE//[^0-9]/}\"}" "$URL/laptop/pair" \
        | python3 -c 'import json, sys; print(json.load(sys.stdin)["key"])') || {
    echo "That code didn't work. Make a new one on the PC and run this again."; exit 1; }
  mkdir -p "$CONF_DIR"
  ( umask 077; printf '{"url": "%s", "key": "%s"}\n' "$URL" "$KEY" > "$CONF_DIR/config.json" )
  echo "Paired."
fi

mkdir -p "$HOME_DIR" "$BIN" "$HOME/.config/systemd/user" "$HOME/.local/share/applications"
curl -fsS "$URL/laptop/satellite.py" -o "$HOME_DIR/satellite.py"
curl -fsS "$URL/laptop/icon.png" -o "$HOME_DIR/jarvis.png" || true

if ! command -v arecord >/dev/null && ! command -v parecord >/dev/null && ! command -v pw-record >/dev/null; then
  say "Installing an audio recorder (needs your password)"
  sudo dnf install -y alsa-utils
fi

# The room microphone: starts at login, restarts if it stops
cat > "$HOME/.config/systemd/user/jarvis-room.service" <<'UNIT'
[Unit]
Description=Jarvis room microphone (talks to the Jarvis on the PC)
After=pipewire.service pipewire-pulse.service

[Service]
ExecStart=/usr/bin/python3 %h/.local/share/jarvis-laptop/satellite.py
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
UNIT

cat > "$BIN/jarvis-room" <<'SCRIPT'
#!/usr/bin/env bash
# jarvis-room on | off | status | log
case "${1:-status}" in
  on)  systemctl --user enable --now jarvis-room && notify-send -i "$HOME/.local/share/jarvis-laptop/jarvis.png" "Jarvis" "Room microphone on" 2>/dev/null || true ;;
  off) systemctl --user disable --now jarvis-room && notify-send -i "$HOME/.local/share/jarvis-laptop/jarvis.png" "Jarvis" "Room microphone off" 2>/dev/null || true ;;
  log) journalctl --user -u jarvis-room -n 40 --no-pager ;;
  *)   systemctl --user is-active jarvis-room ;;
esac
SCRIPT

cat > "$BIN/jarvis-dashboard" <<'SCRIPT'
#!/usr/bin/env bash
# Jarvis's page full screen in its own Firefox profile (Alt+F4 closes it). The key goes in after the #, which the
# browser never sends; the page swaps it for a cookie and removes it from the address.
set -eu
CONF="$HOME/.config/jarvis-laptop/config.json"
read -r URL KEY < <(python3 -c 'import json,sys; c=json.load(open(sys.argv[1])); print(c["url"], c["key"])' "$CONF")
PROFILE="$HOME/.local/share/jarvis-laptop/firefox"
mkdir -p "$PROFILE"
cat > "$PROFILE/user.js" <<'PREFS'
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.tabs.warnOnClose", false);
PREFS
exec firefox --no-remote --profile "$PROFILE" --kiosk "$URL/login#key=$KEY"
SCRIPT
chmod +x "$BIN/jarvis-room" "$BIN/jarvis-dashboard"

cat > "$HOME/.local/share/applications/jarvis.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Jarvis
Comment=Jarvis's dashboard (full screen; Alt+F4 closes it)
Exec=$BIN/jarvis-dashboard
Icon=$HOME_DIR/jarvis.png
Categories=Utility;
Actions=RoomOn;RoomOff;

[Desktop Action RoomOn]
Name=Room microphone on
Exec=$BIN/jarvis-room on

[Desktop Action RoomOff]
Name=Room microphone off
Exec=$BIN/jarvis-room off
DESKTOP

systemctl --user daemon-reload
systemctl --user enable --now jarvis-room
sleep 2
if systemctl --user is-active --quiet jarvis-room; then ROOM="on"; else ROOM="NOT running (see: jarvis-room log)"; fi

say "Done"
cat <<DONE
  Dashboard:        open "Jarvis" from the app grid (Alt+F4 closes it). Pin it to the dash for one click.
  Room microphone:  $ROOM. Say "Jarvis, ..." near the laptop and he answers through its speakers.
                    Right-click the Jarvis icon for Room microphone on/off, or run: jarvis-room off
DONE
