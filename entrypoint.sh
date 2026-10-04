#!/bin/bash
# ==============================================================================
# ENTRYPOINT — Operating Model Initialization Script
# ==============================================================================
set -e

PATH_PREFIX="/relay"
CONFIG_XRAY="/etc/xray/config.json"
CONFIG_SINGBOX="/etc/singbox/config.json"

# 1. Strip JSONC comments from core templates using Python regex (Gojo-Relay style)
python3 -c "
import re
for path in ['/app/core/xray/config.json.template', '/app/core/singbox/config.json.template']:
    with open(path) as f:
        s = f.read()
    s = re.sub(r'(\"(?:\\\\.|[^\"\\\\])*\")|//.*?$|/\*.*?\*/', lambda m: m.group(1) if m.group(1) else '', s, flags=re.MULTILINE|re.DOTALL)
    out_path = path.replace('.template', '')
    with open(out_path, 'w') as f:
        f.write(s)
"

# 2. Get Cloud Run Server IP via metadata server with fallbacks
set +e
SERVER_IP=$(curl -s --max-time 3 -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" 2>/dev/null)
if [ -z "$SERVER_IP" ]; then
  SERVER_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 api.ipify.org || echo "127.0.0.1")
fi
set -e

# 3. UUID Handling: from env, else random/uuid4
if [ -z "${UUID:-}" ]; then
  if [ -f /proc/sys/kernel/random/uuid ]; then
    UUID=$(cat /proc/sys/kernel/random/uuid)
  else
    UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
  fi
fi

# 4. SUFFIX Handling: from env, else 8 random [a-z0-9] chars
if [ -z "${SUFFIX:-}" ]; then
  SUFFIX=$(cat /dev/urandom | tr -dc 'a-z0-9' | head -c 8)
fi

# 5. Build Base Paths and Named Placeholders Substitution
PASSWORD="${PASS:-${UUID}}"
SS_METHOD="${SS:-chacha20-ietf-poly1305}"
SECURITY_SEC="${SEC:-tls}"
ALT_ID="${AID:-0}"
WS_PATH_BASE="${PATH_PREFIX}/${SUFFIX}"

# Replace placeholders in Xray and Sing-box configs
python3 -c "
import os
uuid = os.environ['UUID']
password = os.environ['PASSWORD']
base_path = os.environ['WS_PATH_BASE']
ss_method = os.environ['SS_METHOD']

for cfg_path in ['/etc/xray/config.json', '/etc/singbox/config.json']:
    with open(cfg_path, 'r') as f:
        content = f.read()
    content = content.replace('UUID_PLACEHOLDER', uuid)
    content = content.replace('PASS_PLACEHOLDER', password)
    content = content.replace('SS_METHOD_PLACEHOLDER', ss_method)
    content = content.replace('PATH_PLACEHOLDER', base_path)
    with open(cfg_path, 'w') as f:
        f.write(content)
"

# 6. Chain Outbound Pointing Logic (Gojo-Relay style)
# If IP is provided, configure chain outbounds and prune others; otherwise keep direct/block only.
TARGET_IP="${IP:-}"
TARGET_PORT="${XPORT:-443}"
TARGET_PASS="${PASS:-${UUID}}"
TARGET_PROTO="${PROTO:-vless}"
TARGET_SEC="${SEC:-tls}"
TARGET_XPATH="${XPATH:-/}"
TARGET_SS="${SS:-chacha20-ietf-poly1305}"

if [ -n "$TARGET_IP" ]; then
  python3 -c "
import json, os
ip = os.environ['TARGET_IP']
port = int(os.environ['TARGET_PORT'])
password = os.environ['TARGET_PASS']
proto = os.environ['TARGET_PROTO']
sec = os.environ['TARGET_SEC']
xpath = os.environ['TARGET_XPATH']

# Update Xray Chain Outbound
with open('/etc/xray/config.json', 'r') as f:
    c = json.load(f)

chain_tag = f'chain-{proto}'
for o in c['outbounds']:
    if o['tag'] == chain_tag:
        if proto == 'vless':
            o['settings']['vnext'][0]['address'] = ip
            o['settings']['vnext'][0]['port'] = port
            o['settings']['vnext'][0]['users'][0]['id'] = password
        elif proto == 'vmess':
            o['settings']['vnext'][0]['address'] = ip
            o['settings']['vnext'][0]['port'] = port
            o['settings']['vnext'][0]['users'][0]['id'] = password
        elif proto == 'trojan':
            o['settings']['servers'][0]['address'] = ip
            o['settings']['servers'][0]['port'] = port
            o['settings']['servers'][0]['password'] = password
        elif proto == 'ss':
            o['settings']['servers'][0]['address'] = ip
            o['settings']['servers'][0]['port'] = port
            o['settings']['servers'][0]['password'] = password
        o['streamSettings']['security'] = sec
        o['streamSettings']['wsSettings']['path'] = xpath

keep = ['direct', 'block', chain_tag]
c['outbounds'] = [o for o in c['outbounds'] if o['tag'] in keep]
c['routing']['rules'].append({'type': 'field', 'network': 'tcp,udp', 'outboundTag': chain_tag})

with open('/etc/xray/config.json', 'w') as f:
    json.dump(c, f, indent=2)
"
else
  python3 -c "
import json
with open('/etc/xray/config.json', 'r') as f:
    c = json.load(f)
c['outbounds'] = [o for o in c['outbounds'] if o['tag'] in ['direct', 'block']]
with open('/etc/xray/config.json', 'w') as f:
    json.dump(c, f, indent=2)
"
fi

# 7. Write runtime.json for panel and sub servers
cat > /etc/xray/runtime.json <<EOF
{
  "uuid": "${UUID}",
  "suffix": "${SUFFIX}",
  "path_prefix": "${PATH_PREFIX}",
  "pointed": $([ -n "${TARGET_IP}" ] && echo "true" || echo "false"),
  "server_ip": "${SERVER_IP}"
}
EOF

# 8. Setup SSH Accounts if ACCOUNTS env is provided (X-Sorcerer style)
if [ -n "${ACCOUNTS:-}" ]; then
    IFS=',' read -ra ADDR <<< "$ACCOUNTS"
    for i in "${ADDR[@]}"; do
        U=$(echo "$i" | cut -d: -f1)
        P=$(echo "$i" | cut -d: -f2)
        id -u "$U" >/dev/null 2>&1 || useradd -M -s /bin/false "$U"
        echo "$U:$P" | chpasswd
    done
else
    id -u kyouji >/dev/null 2>&1 || useradd -M -s /bin/false kyouji
    echo "kyouji:kyouji" | chpasswd
fi

# Generate Dropbear host keys if missing
if [ ! -f /etc/dropbear/dropbear_rsa_host_key ]; then
    dropbearkey -t rsa -f /etc/dropbear/dropbear_rsa_host_key -s 2048
fi

# 9. Exec Supervisord
exec /usr/bin/supervisord -c /app/supervisord.conf
