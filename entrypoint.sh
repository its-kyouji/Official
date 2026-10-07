#!/bin/bash
set -e

# =====================================
# ENVIRONMENT & NETWORK INITIALIZATION
# =====================================

export PATH_PREFIX="/kyouji"
export UUID="dba7e194-825f-4740-bb98-1689bc7b7ebc"
export SUFFIX="kyouji"

echo "[INIT] Fetching external IP..."
set +e
export SERVER_IP=$(curl -s --max-time 3 -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" 2>/dev/null)

if [ -z "$SERVER_IP" ]; then
  export SERVER_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 api.ipify.org || echo "127.0.0.1")
fi
set -e

# =============================
# ROUTING & SECRETS ALLOCATION
# =============================

export BASE_PATH="${PATH_PREFIX}/${SUFFIX}"
export IN_PASS="kyouji"
export IN_SS="chacha20-ietf-poly1305"
export EXIT_IP="${IP:-}"
export EXIT_PORT="${XPORT:-443}"
export EXIT_PASS="${PASS:-kyouji}"
export EXIT_PATH="${XPATH:-/}"
export EXIT_PROTO="${PROTO:-vless}"
export EXIT_SS="${SS:-chacha20-ietf-poly1305}"
export EXIT_SEC="${SEC:-tls}"

# ==========================
# CORE ENGINE CONFIGURATION
# ==========================

echo "[INIT] Flattening configurations to /etc and /run/cfg..."

rm -rf /etc/xray/conf
mkdir -p /etc/xray/conf

cp /app/core/xray/00-base/*.json /etc/xray/conf/ 2>/dev/null || true

for d in /app/core/xray/*+*/; do
  [ -d "$d" ] || continue

  n=$(basename "$d")

  cp "$d/inbounds.json" \
    "/etc/xray/conf/20_${n}_inbounds.json"

  if [ -n "$EXIT_IP" ] && [ "${n%%+*}" = "$EXIT_PROTO" ]; then
    cp "$d/chain.json" \
      "/etc/xray/conf/30_${n}_chain.json"
  fi
done

rm -rf /etc/singbox/conf
mkdir -p /etc/singbox/conf

cp /app/core/singbox/00-base/*.json /etc/singbox/conf/ 2>/dev/null || true

for d in /app/core/singbox/*+*/; do
  [ -d "$d" ] || continue

  n=$(basename "$d")

  cp "$d/inbounds.json" \
    "/etc/singbox/conf/20_${n}_inbounds.json"

  if [ -n "$EXIT_IP" ] && [ "${n%%+*}" = "$EXIT_PROTO" ]; then
    cp "$d/chain.json" \
      "/etc/singbox/conf/30_${n}_chain.json"
  fi
done

cp -r /app/connector/. /run/cfg/connector/ 2>/dev/null || true
cp -r /app/relay/. /run/cfg/relay/ 2>/dev/null || true

# ======================
# TEMPLATE SUBSTITUTION
# ======================

echo "[INIT] Processing JSON substitution & stripping..."

python3 -c '
import os
import re
import sys

tokens = {
    "__UUID__": os.environ.get("UUID", ""),
    "__IN_PASS__": os.environ.get("IN_PASS", ""),
    "__IN_SS__": os.environ.get("IN_SS", ""),
    "__BASE_PATH__": os.environ.get("BASE_PATH", ""),
    "__BASE_SVC__": os.environ.get("BASE_PATH", "").lstrip("/"),
    "__EXIT_IP__": os.environ.get("EXIT_IP", ""),
    "__EXIT_PASS__": os.environ.get("EXIT_PASS", ""),
    "__EXIT_PATH__": os.environ.get("EXIT_PATH", ""),
    "__EXIT_SEC__": os.environ.get("EXIT_SEC", ""),
    "__EXIT_SS__": os.environ.get("EXIT_SS", ""),
    "PREFIX_PLACEHOLDER": os.environ.get("PATH_PREFIX", ""),
    "SUFFIX_PLACEHOLDER": os.environ.get("SUFFIX", "")
}

numeric_port = os.environ.get("EXIT_PORT", "443")


def strip_jsonc(text):
    return re.sub(
        r"(\"(?:\\.|[^\"\\])*\")|//.*?$|/\*.*?\*/",
        lambda m: m.group(1) if m.group(1) else "",
        text,
        flags=re.MULTILINE | re.DOTALL
    )


dirs_to_process = [
    "/etc/xray/conf",
    "/etc/singbox/conf",
    "/run/cfg"
]

for d in dirs_to_process:
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)

            with open(p, "r") as file:
                content = file.read()

            if p.endswith(".json"):
                content = strip_jsonc(content)

            content = content.replace(
                "\"__EXIT_PORT__\"",
                numeric_port
            )

            for k, v in tokens.items():
                content = content.replace(k, v)

            leftovers = re.findall(
                r"__[A-Z_]+__",
                content
            )

            if leftovers:
                print(
                    f"[FATAL] Leftover token(s) "
                    f"{leftovers} found in {p}"
                )
                sys.exit(1)

            with open(p, "w") as file:
                file.write(content)
'

# =================
# RUNTIME METADATA
# =================
echo "[INIT] Writing runtime.json..."

cat > /etc/xray/runtime.json <<EOF
{
  "uuid": "${UUID}",
  "suffix": "${SUFFIX}",
  "path_prefix": "${PATH_PREFIX}",
  "pointed": $([ -n "${TARGET_IP}" ] && echo "true" || echo "false"),
  "server_ip": "${SERVER_IP}"
}
EOF

echo "[INIT] Configuring SSH accounts..."

# === DROPBEAR SHELL AUTHORIZATION ===
if ! grep -q "/bin/false" /etc/shells; then
  echo "/bin/false" >> /etc/shells
fi

# === BADVPN DNS RESOLVER FIX (VALIDATED) ===
if ! grep -q "8.8.8.8" /etc/resolv.conf; then
  echo "options rotate timeout:1" >> /etc/resolv.conf  
        # Google DNS
  echo "nameserver 8.8.8.8" >> /etc/resolv.conf
        # Cloudflare DNS
  echo "nameserver 1.1.1.1" >> /etc/resolv.conf
fi

# === SSH ACCOUNT CREDENTIALS (Default) ===
ACCOUNTS="${ACCOUNTS:-kyouji:kyouji}"

echo "$ACCOUNTS" | tr ',' '\n' |
while IFS=: read -r u p; do
  [ -z "$u" ] || [ -z "$p" ] && continue

  id -u "$u" >/dev/null 2>&1 ||
    useradd -M -s /bin/false "$u"

  echo "$u:$p" | chpasswd
done

# === SSH HOST KEY PROVISIONING ===
if [ ! -f /etc/dropbear/dropbear_rsa_host_key ]; then
  mkdir -p /etc/dropbear

  dropbearkey \
    -t rsa \
    -f /etc/dropbear/dropbear_rsa_host_key \
    -s 2048 >/dev/null 2>&1
fi

ssh-keygen -A >/dev/null 2>&1

# ==================
# PRE-FLIGHT CHECKS
# ==================

echo "[INIT] Pre-flight config tests..."

FAIL=0

# Xray
/usr/local/bin/xray run \
  -test \
  -confdir /etc/xray/conf || FAIL=1
  
# Sing-box
/usr/local/bin/sing-box check \
  -C /etc/singbox/conf || FAIL=1

# HAProxy
/usr/sbin/haproxy \
  -c \
  -f /run/cfg/connector/haproxy/haproxy.cfg || FAIL=1

# Envoy
envoy \
  --mode validate \
  -c /run/cfg/connector/envoy/envoy.yaml || FAIL=1

# Nginx
nginx \
  -t \
  -c /run/cfg/connector/nginx/nginx.conf || FAIL=1

# Caddy
caddy validate \
  --config /run/cfg/connector/caddy/Caddyfile \
  --adapter caddyfile || FAIL=1

# Python relay
python3 \
  -m py_compile \
  /run/cfg/relay/*.py || FAIL=1

[ "$FAIL" -eq 0 ] || {
  echo "[INIT][FATAL] Pre-flight tests failed!"
  exit 1
}

echo "[INIT] Initialization complete. Starting Supervisord..."

exec /usr/bin/supervisord \
  -c /app/supervisord.conf
