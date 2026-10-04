#!/bin/bash
# ==============================================================================
# ENTRYPOINT — Plug-and-Play Initialization Script
# ==============================================================================
set -e

PATH_PREFIX="/relay"

# 1. Strip JSONC comments from core templates
python3 -c "
import re
for path in ['/app/core/xray/config.json.template', '/app/core/singbox/config.json.template']:
    with open(path) as f: s = f.read()
    s = re.sub(r'(\"(?:\\\\.|[^\"\\\\])*\")|//.*?$|/\*.*?\*/', lambda m: m.group(1) if m.group(1) else '', s, flags=re.MULTILINE|re.DOTALL)
    with open(path.replace('.template', ''), 'w') as f: f.write(s)
"

# 2. Get Cloud Run Server IP via metadata server with fallbacks
set +e
export SERVER_IP=$(curl -s --max-time 3 -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip" 2>/dev/null)
if [ -z "$SERVER_IP" ]; then
  export SERVER_IP=$(curl -s --max-time 5 ifconfig.me || curl -s --max-time 5 api.ipify.org || echo "127.0.0.1")
fi
set -e

# 3. Awtomatikong mag-generate ng UUID kapag walang nilagay ang user (Plug-and-play)
if [ -z "${UUID:-}" ]; then
  if [ -f /proc/sys/kernel/random/uuid ]; then
    export UUID=$(cat /proc/sys/kernel/random/uuid)
  else
    export UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
  fi
fi

# 4. Awtomatikong mag-generate ng SUFFIX kapag walang nilagay ang user
if [ -z "${SUFFIX:-}" ]; then
  export SUFFIX=$(cat /dev/urandom | tr -dc 'a-z0-9' | head -c 8)
fi

# 5. Set default fallback credentials
export PASSWORD="${PASS:-${UUID}}"
export SS_METHOD="${SS:-chacha20-ietf-poly1305}"
export WS_PATH_BASE="${PATH_PREFIX}/${SUFFIX}"

# I-inject ang generated UUID, PASS, at PATH sa mga config
python3 -c "
import os
uuid = os.environ['UUID']
password = os.environ['PASSWORD']
base_path = os.environ['WS_PATH_BASE']
ss_method = os.environ['SS_METHOD']

for cfg_path in ['/etc/xray/config.json', '/etc/singbox/config.json']:
    with open(cfg_path, 'r') as f: content = f.read()
    content = content.replace('UUID_PLACEHOLDER', uuid).replace('PASS_PLACEHOLDER', password)
    content = content.replace('SS_METHOD_PLACEHOLDER', ss_method).replace('PATH_PLACEHOLDER', base_path)
    with open(cfg_path, 'w') as f: f.write(content)
"

# 6. Chain Outbound Pointing Logic
export TARGET_IP="${IP:-}"
export TARGET_PORT="${XPORT:-443}"
export TARGET_PASS="${PASS:-${UUID}}"
export TARGET_PROTO="${PROTO:-vless}"
export TARGET_SEC="${SEC:-tls}"
export TARGET_XPATH="${XPATH:-/}"

if [ -n "$TARGET_IP" ]; then
  python3 -c "
import json, os
ip, port, password = os.environ['TARGET_IP'], int(os.environ['TARGET_PORT']), os.environ['TARGET_PASS']
proto, sec, xpath = os.environ['TARGET_PROTO'], os.environ['TARGET_SEC'], os.environ['TARGET_XPATH']

with open('/etc/xray/config.json', 'r') as f: c = json.load(f)

chain_tag = f'chain-{proto}'
for o in c['outbounds']:
    if o['tag'] == chain_tag:
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

c['outbounds'] = [o for o in c['outbounds'] if o['tag'] in ['direct', 'block', chain_tag]]
c['routing']['rules'].append({'type': 'field', 'network': 'tcp,udp', 'outboundTag': chain_tag})
with open('/etc/xray/config.json', 'w') as f: json.dump(c, f, indent=2)
"
else
  python3 -c "
import json
with open('/etc/xray/config.json', 'r') as f: c = json.load(f)
c['outbounds'] = [o for o in c['outbounds'] if o['tag'] in ['direct', 'block']]
with open('/etc/xray/config.json', 'w') as f: json.dump(c, f, indent=2)
"
fi

# 7. Write runtime.json
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
id -u kyouji >/dev/null 2>&1 || useradd -M -s /bin/false kyouji
echo "kyouji:kyouji" | chpasswd

if [ ! -f /etc/dropbear/dropbear_rsa_host_key ]; then
    dropbearkey -t rsa -f /etc/dropbear/dropbear_rsa_host_key -s 2048
fi

# 9. Exec Supervisord
exec /usr/bin/supervisord -c /app/supervisord.conf
