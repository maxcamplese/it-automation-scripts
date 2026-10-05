#!/usr/bin/env bash
#
# net-check.sh: Check DNS and internet connectivity, and explain the result
# in plain language for someone who is not technical.
#
# It tests each layer in order, because a failure at one layer explains
# every failure after it:
#   1. Is there a network connection at all (a default gateway)?
#   2. Can we reach the router?
#   3. Can we reach the internet by IP address (no DNS needed)?
#   4. Can we turn a name like example.com into an address (DNS)?
#   5. Can we load a real website over HTTPS?
#
# Usage:
#   ./scripts/net-check.sh              # plain-language report
#   ./scripts/net-check.sh --details    # also show IP addresses and DNS servers
#   ./scripts/net-check.sh --help
#   NET_CHECK_DOMAIN=yourcompany.com ./scripts/net-check.sh   # test a specific domain
#
# Exit codes: 0 = everything passed, 1 = at least one check failed, 2 = unknown option.
# Works on macOS and Linux. Uses only built-in tools (ping, curl, dig or nslookup).

set -u

PUBLIC_IP="1.1.1.1"             # Cloudflare's public DNS server, used as a reachability target
TEST_NAME="${NET_CHECK_DOMAIN:-example.com}"   # example.com is reserved for testing and always exists
TEST_URL="https://$TEST_NAME"

SHOW_DETAILS=false
FAILURES=0

usage() {
  sed -n '3,21p' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-}" in
  --details) SHOW_DETAILS=true ;;
  --help|-h) usage; exit 0 ;;
  "") ;;
  *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
esac

pass() { printf '  [PASS] %s\n' "$1"; }
fail() { printf '  [FAIL] %s\n' "$1"; printf '         What this means: %s\n' "$2"; FAILURES=$((FAILURES + 1)); }
warn() { printf '  [WARN] %s\n' "$1"; printf '         What this means: %s\n' "$2"; }
detail() { if $SHOW_DETAILS; then printf '         %s\n' "$1"; fi; }

# ping once with a short timeout. The timeout flag differs between macOS and Linux.
ping_once() {
  if [ "$(uname)" = "Darwin" ]; then
    ping -c 1 -t 3 "$1" >/dev/null 2>&1
  else
    ping -c 1 -W 3 "$1" >/dev/null 2>&1
  fi
}

default_gateway() {
  if [ "$(uname)" = "Darwin" ]; then
    route -n get default 2>/dev/null | awk '/gateway:/ {print $2}'
  else
    ip route 2>/dev/null | awk '/^default/ {print $3; exit}'
  fi
}

# Prints the first address a name resolves to, or nothing if DNS fails.
resolve_name() {
  if command -v dig >/dev/null 2>&1; then
    dig +short +time=3 +tries=1 "$1" A 2>/dev/null | grep -E '^[0-9.]+$' | head -n 1
  else
    nslookup "$1" 2>/dev/null | awk '/^Address: / {print $2}' | grep -E '^[0-9.]+$' | head -n 1
  fi
}

echo "Network check ($(date '+%Y-%m-%d %H:%M'))"
echo

# 1. Network connection
gateway="$(default_gateway)"
if [ -n "$gateway" ]; then
  pass "This computer is connected to a network."
  detail "Default gateway: $gateway"
else
  fail "This computer is not connected to any network." \
       "Wi-Fi may be off or not joined, or the cable is unplugged. Every check below will fail too."
fi

# 2. Router
if [ -n "$gateway" ] && ping_once "$gateway"; then
  pass "The router answered."
elif [ -n "$gateway" ]; then
  # Many routers (and most campus or office networks) block ping on purpose,
  # so this is a warning, not a failure. The next checks decide.
  warn "The router did not answer a ping." \
       "Many networks block ping on purpose. If the checks below pass, ignore this."
fi

# 3. Internet by IP address. Try ping first. Some networks block ping, so
# fall back to an HTTPS request straight to the IP, which also skips DNS.
if ping_once "$PUBLIC_IP"; then
  pass "The internet is reachable."
  detail "Pinged $PUBLIC_IP"
elif curl -s -o /dev/null -m 5 "https://$PUBLIC_IP"; then
  pass "The internet is reachable."
  detail "Ping to $PUBLIC_IP was blocked, but HTTPS to it worked"
else
  fail "The internet is not reachable." \
       "The local network works but the connection to the outside does not. Restart the router or check for an outage."
fi

# 4. DNS
address="$(resolve_name "$TEST_NAME")"
if [ -n "$address" ]; then
  pass "Website names are being looked up correctly (DNS works for $TEST_NAME)."
  detail "$TEST_NAME resolved to $address"
else
  if [ -n "${NET_CHECK_DOMAIN:-}" ]; then
    # A custom domain can fail because the name is wrong, not because DNS is broken.
    fail "Website names cannot be looked up (DNS failed for $TEST_NAME)." \
         "Check the spelling. If it is right, the domain's DNS records may be missing or expired. Try again without NET_CHECK_DOMAIN to test DNS in general."
  else
    fail "Website names cannot be looked up (DNS failed for $TEST_NAME)." \
         "Sites will not load by name even if the internet is up. Try turning Wi-Fi off and on, or ask IT about the DNS settings."
  fi
fi
if $SHOW_DETAILS && [ -r /etc/resolv.conf ]; then
  detail "DNS servers in use: $(awk '/^nameserver/ {printf "%s ", $2}' /etc/resolv.conf)"
fi

# 5. HTTPS. Skipped when DNS failed, because it cannot work without DNS and a
# second failure would only add noise.
if [ -z "$address" ]; then
  printf '  [SKIP] Secure website check skipped because DNS failed.\n'
elif curl -s -o /dev/null -m 8 "$TEST_URL"; then
  pass "Secure websites load."
else
  fail "A secure website did not load." \
       "If DNS and internet passed, a firewall, proxy, VPN, or the computer's clock may be blocking secure connections."
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "Result: everything looks fine. If one site still will not load, the problem is probably that site."
  exit 0
else
  echo "Result: $FAILURES check(s) failed. Start with the first [FAIL] above; it usually explains the rest."
  exit 1
fi
