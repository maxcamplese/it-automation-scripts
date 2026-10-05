#!/usr/bin/env bash
#
# wifi-summary.sh: Summarize this Mac's current Wi-Fi connection and say,
# in plain language, whether the signal is good enough.
#
# It reads `system_profiler SPAirPortDataType`, which is built into macOS.
# Apple removed the old `airport` command in macOS 14.4, so this is the
# supported way to get signal, noise, channel, and security without sudo.
#
# Usage:
#   ./scripts/wifi-summary.sh
#   ./scripts/wifi-summary.sh --help
#
# Exit codes: 0 = connected, 1 = not connected or not a Mac.
#
# Note: newer macOS versions hide the network name (SSID) unless the app
# running the script has Location Services permission. The script then says
# the name is hidden and reports everything else.

set -u

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

if [ "$(uname)" != "Darwin" ]; then
  echo "This script only runs on macOS." >&2
  exit 1
fi

report="$(system_profiler SPAirPortDataType 2>/dev/null)"

# The current connection is the block under "Current Network Information:".
# Stop reading at "Other Local Wi-Fi Networks:" so we do not pick up neighbors.
current="$(printf '%s\n' "$report" | awk '
  /Current Network Information:/ {found=1; next}
  /Other Local Wi-Fi Networks:/  {found=0}
  found {print}
')"

if [ -z "$current" ]; then
  echo "Wi-Fi is on but not connected to a network (or Wi-Fi is off)."
  echo "What to do: click the Wi-Fi icon in the menu bar and join a network."
  exit 1
fi

# Pull one field out of the current-network block, e.g. field "Channel".
field() {
  printf '%s\n' "$current" | awk -F': ' -v key="$1" '$1 ~ key {print $2; exit}'
}

ssid="$(printf '%s\n' "$current" | head -n 1 | sed 's/^ *//; s/:$//')"
# macOS puts a token in angle brackets where the name would be when it hides it.
case "$ssid" in
  "<"*">") ssid="(hidden by macOS; allow Location Services for Terminal to show it)" ;;
esac
phy="$(field 'PHY Mode')"
channel="$(field 'Channel')"
security="$(field 'Security')"
rate="$(field 'Transmit Rate')"
signal_noise="$(field 'Signal / Noise')"

# "Signal / Noise: -57 dBm / -96 dBm" -> signal=-57, noise=-96
signal="$(printf '%s' "$signal_noise" | awk '{print $1}')"
noise="$(printf '%s' "$signal_noise" | awk '{print $4}')"

echo "Wi-Fi summary ($(date '+%Y-%m-%d %H:%M'))"
echo
echo "  Network:        ${ssid:-unknown}"
echo "  Standard:       ${phy:-unknown}"
echo "  Channel/band:   ${channel:-unknown}"
echo "  Security:       ${security:-unknown}"
echo "  Link speed:     ${rate:-unknown} Mbps"
echo "  Signal / noise: ${signal_noise:-unknown}"
echo

# Signal strength (RSSI) is negative; closer to 0 is stronger.
# These thresholds are common rules of thumb, not hard limits.
if [ -n "$signal" ]; then
  if [ "$signal" -ge -60 ]; then
    echo "  Signal: strong. Video calls and large downloads should work well."
  elif [ "$signal" -ge -70 ]; then
    echo "  Signal: fair. Browsing is fine; video calls may stutter."
  else
    echo "  Signal: weak. Move closer to the access point or remove obstacles."
  fi
fi

# Signal-to-noise ratio: how far the signal stands above background noise.
if [ -n "$signal" ] && [ -n "$noise" ]; then
  snr=$((signal - noise))
  if [ "$snr" -ge 25 ]; then
    echo "  Interference: low (SNR ${snr} dB)."
  elif [ "$snr" -ge 15 ]; then
    echo "  Interference: moderate (SNR ${snr} dB). Nearby networks or devices may slow things down."
  else
    echo "  Interference: high (SNR ${snr} dB). Expect drops; try a different band or location."
  fi
fi

case "$channel" in
  *2GHz*) echo "  Band: 2.4 GHz. Longer range but slower and more crowded. Use 5 or 6 GHz if available." ;;
  *5GHz*) echo "  Band: 5 GHz. Good balance of speed and range." ;;
  *6GHz*) echo "  Band: 6 GHz. Fastest and least crowded, but shorter range through walls." ;;
esac

case "$security" in
  None|"") echo "  Security: this network is open. Avoid signing in to anything sensitive without a VPN." ;;
  *WEP*)   echo "  Security: WEP is outdated and easy to break. The network should be upgraded." ;;
esac

exit 0
