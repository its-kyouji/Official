#!/bin/bash
# ==============================================================================
# ENTRYPOINT — Resilient Initialization Script
# ==============================================================================
set -e

PATH_PREFIX="/relay"

echo "[INIT] Starting container initialization..."

# 1. Strip JSONC comments from core templates
echo "[INIT] Stripping JSONC comments..."
python3 -c "
import re, sys
try:
    for path in ['/app/core/xray/config.json.template', '/app/core/singbox/config.json.template']:
        with open(path) as f: s = f.read()
        s = re.sub(r'(\"(?:\\\\.|[^\"\\\\])*\")|//.*?$|/\*.*?\*/', lambda m: m.group(1) if m.group(1) else '', s, flags=re.MULTILINE|re.DOTALL)
        with open(path.replace('.template', ''), 'w') as f: f.write(s)
except Exception as e:
    print(f'Error stripping comments: {e}')
    sys.exit(1)
"

# 2. Get Cloud Run Server IP via metadata server with fallbacks
echo "[INIT] Fetching external IP..."
set +e
export SERVER_IP=$(curl -s --max-time 3 -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" 2>/dev/null)
if [ -z "$SERVER_IP" ]; then
  export SERVER_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 api.ipify.org || echo "127.0.0.1")
fi
set -e
echo "[INIT] Server IP resolved to: $SERVER_IP"

# 3. Handle UUID
if [ -z "${UUID:-}" ]; then
  if [ -f /proc/sys/kernel/random/uuid ]; then
    export UUID=$(cat /proc/sys/kernel/random/uuid)
  else
    export UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
  fi
fi
echo "[INIT] Using UUID: $UUID"

# 4. Handle SUFFIX
if [ -z "${SUFFIX:-}" ]; then
  export SUFFIX=$(cat /dev/urandom | tr -dc 'a-z0-9' | head -c 8)
fi

# 5. Build Base Paths and Named Placeholders Substitution
export PASSWORD="${PASS:-${UUID}}"
export SS_METHOD="${SS:-chacha20-ietf-poly1305}"
export WS_PATH_BASE="${PATH_PREFIX}/${SUFFIX}"

echo "[INIT] Injecting placeholders into configs..."
python3 -c "
import os, sys
try:
    uuid = os.environ.get('UUID', '')
    password = os.environ.get('PASSWORD', '')
    base_path = os.environ.get('WS_PATH_BASE', '')
    ss_method = os.environ.get('SS_METHOD', '')

    for cfg_path in ['/etc/xray/config.json', '/etc/singbox/config.json']:
        with open(cfg_path, 'r') as f: content = f.read()
        content = content.replace('UUID_PLACEHOLDER', uuid).replace('PASS_PLACEHOLDER', password)
        content = content.replace('SS_METHOD_PLACEHOLDER', ss_method).replace('PATH_PLACEHOLDER', base_path)
        with open(cfg_path, 'w') as f: f.write(content)
except Exception as e:
    print(f'Error injecting placeholders: {e}')
    sys.exit(1)
"

# 6. Chain Outbound Pointing Logic
export TARGET_IP="${IP:-}"
export TARGET_PORT="${XPORT:-443}"
export TARGET_PASS="${PASS:-${UUID}}"
export TARGET_PROTO="${PROTO:-vless}"
export TARGET_SEC="${SEC:-tls}"
export TARGET_XPATH="${XPATH:-/}"

echo "[INIT] Processing outbound chains..."
if [ -n "$TARGET_IP" ]; then
  python3 -c "
import json, os, sys
try:
    ip = os.environ.get('TARGET_IP', '')
    port = int(os.environ.get('TARGET_PORT', '443'))
    password = os.environ.get('TARGET_PASS', '')
    proto = os.environ.get('TARGET_PROTO', 'vless')
    sec = os.environ.get('TARGET_SEC', 'tls')
    xpath = os.environ.get('TARGET_XPATH', '/')

    with open('/etc/xray/config.json', 'r') as f: c = json.load(f)

    chain_tag = f'chain-{proto}'
    for o in c.get('outbounds', []):
        if o.get('tag') == chain_tag:
            if proto in ['vless', 'vmess']:
                o['settings']['vnext'][0]['address'] = ip
                o['settings']['vnext'][0]['port'] = port
                o['settings']['vnext'][0]['users'][0]['id'] = password
            elif proto in ['trojan', 'shadowsocks']:
                o['settings']['servers'][0]['address'] = ip
                o['settings']['servers'][0]['port'] = port
                o['settings']['servers'][0]['password'] = password
            o['streamSettings']['security'] = sec
            o['streamSettings']['wsSettings']['path'] = xpath

    c['outbounds'] = [o for o in c.get('outbounds', []) if o.get('tag') in ['direct', 'block', chain_tag]]
    if 'routing' in c and 'rules' in c['routing']:
        c['routing']['rules'].append({'type': 'field', 'network': 'tcp,udp', 'outboundTag': chain_tag})
    
    with open('/etc/xray/config.json', 'w') as f: json.dump(c, f, indent=2)
except Exception as e:
    print(f'Error processing chain logic: {e}')
    sys.exit(1)
"
else
  python3 -c "
import json, sys
try:
    with open('/etc/xray/config.json', 'r') as f: c = json.load(f)
    c['outbounds'] = [o for o in c.get('outbounds', []) if o.get('tag') in ['direct', 'block']]
    with open('/etc/xray/config.json', 'w') as f: json.dump(c, f, indent=2)
except Exception as e:
    print(f'Error removing chain logic: {e}')
    sys.exit(1)
"
fi

# 7. Write runtime.json
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

# 8. Setup Default SSH Account
echo "[INIT] Configuring internal SSH accounts..."
id -u kyouji >/dev/null 2>&1 || useradd -M -s /bin/false kyouji
echo "kyouji:kyouji" | chpasswd

if [ ! -f /etc/dropbear/dropbear_rsa_host_key ]; then
    dropbearkey -t rsa -f /etc/dropbear/dropbear_rsa_host_key -s 2048 >/dev/null 2>&1
fi

echo "[INIT] Initialization complete. Starting Supervisord..."
# 9. Exec Supervisord
exec /usr/bin/supervisord -c /app/supervisord.conf
