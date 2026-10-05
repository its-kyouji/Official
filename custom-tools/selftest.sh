#!/bin/bash
echo "[SELFTEST] Running Pre-flight tests..."
FAIL=0
/usr/local/bin/xray run -test -confdir /etc/xray/conf || FAIL=1
/usr/local/bin/sing-box check -C /etc/singbox/conf || FAIL=1
haproxy -c -f /run/cfg/connector/haproxy/haproxy.cfg || FAIL=1
envoy --mode validate -c /run/cfg/connector/envoy/envoy.yaml || FAIL=1
nginx -t -c /run/cfg/connector/nginx/nginx.conf || FAIL=1
caddy validate --config /run/cfg/connector/caddy/Caddyfile --adapter caddyfile || FAIL=1

echo -e "\n[SELFTEST] Checking listening ports..."
for port in 8080 8081 8082 8083 8084 10001 10005 10009 10013 11001 11004 11007 2200 2201 2222 2223; do
  nc -z 127.0.0.1 $port && echo "Port $port: UP" || { echo "Port $port: DOWN"; FAIL=1; }
done

echo -e "\n[SELFTEST] Running smoke tests..."
C_HTTP1=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/health)
C_HTTP2=$(curl --http2-prior-knowledge -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/health 2>/dev/null)

printf "\n%-20s | %-10s\n" "LANE / TEST" "RESULT"
printf -- "---------------------+------------\n"
printf "%-20s | %-10s\n" "Pre-flight Configs" $([ $FAIL -eq 0 ] && echo "PASS" || echo "FAIL")
printf "%-20s | %-10s\n" "HTTP/1.1 (/health)" $([ "$C_HTTP1" == "200" ] && echo "PASS" || echo "FAIL")
printf "%-20s | %-10s\n" "h2c gRPC (/health)" $([ "$C_HTTP2" == "200" ] && echo "PASS" || echo "FAIL")

echo -e "\n==== UNVERIFIED ITEMS ===="
echo "1. gRPC serviceName path shape: Verify if proxies accept -grpc or -grpc/Tun."
echo "   Fix: Test with real client. Adjust HAProxy regex if needed."
echo "2. XHTTP wire paths downgrade: Verify if XHTTP works over downgraded HTTP/1.1."
echo "   Fix: Monitor Cloud Run logs during XHTTP client connection."
echo "3. Cleartext h1 to h2c auto-upgrade in HAProxy 2.x on Debian Bookworm."
echo "   Fix: Test 'curl --http2-prior-knowledge' against HAProxy port directly."
echo "4. OVPN Bridge setup: Lacks remote VM OpenVPN target integration."
echo "   Fix: Provision external VM and inject details to bridge-ovpn.json."
echo "5. Sing-box array merge order: Verify if chain.json loads first."
echo "   Fix: sing-box merge /tmp/out.json -C /etc/singbox/conf && cat /tmp/out.json"
