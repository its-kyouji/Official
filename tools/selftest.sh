#!/bin/bash
# ==== SELFTEST.SH ====
# I built this to mandate pre-flight checks. Runs syntax validation against 
# all generated configurations and tests active loopback listeners.

BOLD='\033[1m'
GREEN='\033[1;32m'
RED='\033[1;31m'
YELLOW='\033[1;33m'
RESET='\033[0m'

echo -e "${BOLD}=== OFFICIAL RELAY SELF-TEST ===${RESET}\n"

printf "%-25s %-15s %s\n" "COMPONENT" "STATUS" "DETAILS"
printf "%-25s %-15s %s\n" "---------" "------" "-------"

# 1. Config Syntax Validations
check_syntax() {
    local name="$1"
    local cmd="$2"
    local output
    if output=$(eval "$cmd" 2>&1); then
        printf "%-25s ${GREEN}%-15s${RESET} %s\n" "$name Syntax" "[PASS]" "Configuration valid"
    else
        printf "%-25s ${RED}%-15s${RESET} %s\n" "$name Syntax" "[FAIL]" "Syntax error detected"
        echo -e "${YELLOW}Log:${RESET} $output"
    fi
}

check_syntax "Xray" "xray run -test -config /etc/xray/config.json"
check_syntax "Sing-box" "sing-box check -c /etc/singbox/config.json"
check_syntax "Nginx" "nginx -t -c /etc/nginx/nginx.conf"
check_syntax "HAProxy" "haproxy -c -f /etc/haproxy/haproxy.cfg"
check_syntax "Envoy" "envoy --mode validate -c /etc/envoy/envoy.yaml"
check_syntax "Caddy" "caddy validate --config /etc/caddy/Caddyfile"

# 2. Port Listener Checks
check_port() {
    local name="$1"
    local port="$2"
    if nc -z 127.0.0.1 "$port" 2>/dev/null; then
        printf "%-25s ${GREEN}%-15s${RESET} %s\n" "$name (:$port)" "[PASS]" "Port is listening"
    else
        printf "%-25s ${RED}%-15s${RESET} %s\n" "$name (:$port)" "[FAIL]" "Port NOT listening"
    fi
}

echo ""
check_port "Fortress (Edge)" "8080"
check_port "Envoy (Shield)" "8081"
check_port "HAProxy (Router)" "8082"
check_port "Nginx (WS)" "8083"
check_port "Caddy (HU/XH)" "8084"
check_port "Xray Base" "10000"

echo -e "\n${BOLD}=== UNVERIFIED ZONES ===${RESET}"
echo -e "${YELLOW}1. gRPC/h2c routing via Fortress/Envoy requires real-world Cloud Run traffic to verify L7 LB bypass.${RESET}"
echo -e "${YELLOW}2. Caddy 'flush_interval -1' for XHTTP stream-one needs load testing.${RESET}"
echo -e "${YELLOW}3. OVPN Relay relies on external host availability ($OVPN_UPSTREAM).${RESET}\n"
