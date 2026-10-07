# Port Mapping (Strictly Unique)
# Example and this is experimental not official yet.
- 8080: Cloud Run Target (Fortress Shield)
- 8081: Envoy Proxy (h2c/gRPC handler)
- 8082: HAProxy (L7 Router)
- 8083: Nginx (WS/HU lane & Panel)
- 8084: Caddy (XHTTP lane)
- 10001-10004: Xray VLESS (ws, hu, xh, grpc)
- 10005-10008: Xray VMESS (ws, hu, xh, grpc)
- 10009-10012: Xray TROJAN (ws, hu, xh, grpc)
- 10013-10016: Xray SS (ws, hu, xh, grpc)
- 11001-11003: Sing-box VLESS (ws, hu, grpc)
- 11004-11006: Sing-box VMESS (ws, hu, grpc)
- 11007-11009: Sing-box TROJAN (ws, hu, grpc)
- 2200: Dropbear local
- 2201: OpenSSH local
- 2222: Bridge Dropbear
- 2223: Bridge OpenSSH
- 2224: Bridge OVPN
