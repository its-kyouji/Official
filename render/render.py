#!/usr/bin/env python3
# ==== RENDER.PY ====
# Master configuration generator. Reads routes.yaml and environment variables to
# construct deterministic configurations for Envoy, HAProxy, Nginx, Caddy, Xray,
# and Sing-box. Executed strictly once during container initialization.

import os
import yaml
import json
import uuid
import hashlib

def get_env(key, default=""):
    return os.environ.get(key, default)

def generate_configs():
    # --- Environment Extraction ---
    sys_uuid = get_env("UUID")
    if not sys_uuid:
        sys_uuid = str(uuid.uuid4())
        print(f"[RENDER] No UUID provided. Generated ephemeral UUID: {sys_uuid}")
    
    password = get_env("PASSWORD", "default-secret")
    base_path = get_env("BASE_PATH", "/relay").rstrip('/')
    ads_mode = get_env("ADS_MODE", "normal")
    cores = get_env("CORES", "xray").split(",")
    ovpn_upstream = get_env("OVPN_UPSTREAM", "")
    
    # --- Load Master Routes ---
    with open('/app/routes.yaml', 'r') as f:
        routes = yaml.safe_load(f).get('routes', [])

    fortress_whitelist = ["/health"]
    bridge_mapping = []
    
    # Proxy specific accumulators
    haproxy_acls_ws = []
    haproxy_acls_caddy = []
    haproxy_acls_grpc = []
    haproxy_backends = []
    
    nginx_locations = []
    caddy_handles = []
    
    xray_inbounds = []
    singbox_inbounds = []

    for route in routes:
        core = route.get('core')
        proto = route.get('protocol')
        trans = route.get('transport')
        port = route.get('port')
        target_port = route.get('target_port')
        proxy = route.get('proxy')
        
        endpoint_path = f"{base_path}-{core}-{proto}-{trans}"
        fortress_whitelist.append(endpoint_path)

        # --- Bridge Handling (SSH/OVPN) ---
        if core in ["ssh", "ovpn"]:
            bridge_mapping.append({
                "listen": port,
                "target_host": ovpn_upstream if core == "ovpn" else "127.0.0.1",
                "target_port": target_port,
                "label": f"{core}-{trans}"
            })
            if proxy == "nginx":
                nginx_locations.append(f"""
        location ^~ {endpoint_path} {{
            proxy_pass http://127.0.0.1:{port};
            proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade; proxy_set_header Host $host;
            proxy_read_timeout 3600s; proxy_send_timeout 3600s;
            proxy_buffering off; proxy_request_buffering off; proxy_socket_keepalive on;
        }}""")
                haproxy_acls_ws.append(f"    acl path_{core}_{trans} path_beg {endpoint_path}\n    use_backend bk_nginx if path_{core}_{trans}")
            elif proxy == "caddy":
                caddy_handles.append(f"""
    handle {endpoint_path}* {{
        reverse_proxy 127.0.0.1:{port} {{ flush_interval -1 
            transport http {{ versions h1 h2c 2 }}
        }}
    }}""")
                haproxy_acls_caddy.append(f"    acl path_{core}_{trans} path_beg {endpoint_path}\n    use_backend bk_caddy if path_{core}_{trans}")
            continue

        # --- Xray Generation ---
        if core == "xray":
            inbound = {
                "port": port, "listen": "127.0.0.1", "protocol": proto, "tag": f"in-{proto}-{trans}",
                "streamSettings": {"sockopt": {"tcpFastOpen": True, "tcpNoDelay": True, "tcpKeepAliveInterval": 15}},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            }
            if trans == "ws":
                inbound["streamSettings"].update({"network": "ws", "wsSettings": {"path": endpoint_path}})
            elif trans == "hu":
                inbound["streamSettings"].update({"network": "httpupgrade", "httpupgradeSettings": {"path": endpoint_path}})
            elif trans == "xh":
                inbound["streamSettings"].update({"network": "xhttp", "xhttpSettings": {"path": endpoint_path, "mode": "auto"}})
            elif trans == "grpc":
                inbound["streamSettings"].update({"network": "grpc", "grpcSettings": {"serviceName": endpoint_path.lstrip('/')}})

            if proto in ["vless", "vmess"]:
                inbound["settings"] = {"clients": [{"id": sys_uuid}], "decryption": "none" if proto == "vless" else None}
            elif proto == "trojan":
                inbound["settings"] = {"clients": [{"password": password}]}
            elif proto == "ss":
                inbound["settings"] = {"clients": [{"password": password, "method": "aes-256-gcm"}]}
            xray_inbounds.append(inbound)

        # --- Sing-box Generation ---
        if core == "singbox":
            inbound = {
                "type": proto, "tag": f"in-{proto}-{trans}",
                "listen": "127.0.0.1", "listen_port": port,
                "tcp_fast_open": True, "sniff": True, "sniff_override_destination": True
            }
            if proto in ["vless", "vmess"]:
                inbound["users"] = [{"uuid": sys_uuid}]
            elif proto == "trojan":
                inbound["users"] = [{"password": password}]
            elif proto == "ss":
                inbound["method"] = "aes-256-gcm"
                inbound["password"] = password

            if trans == "ws":
                inbound["transport"] = {"type": "ws", "path": endpoint_path}
            elif trans == "hu":
                inbound["transport"] = {"type": "httpupgrade", "path": endpoint_path}
            elif trans == "grpc":
                inbound["transport"] = {"type": "grpc", "service_name": endpoint_path.lstrip('/')}
            singbox_inbounds.append(inbound)

        # --- Reverse Proxy Fabric Generation ---
        if proxy == "nginx":
            nginx_locations.append(f"""
        location ^~ {endpoint_path} {{
            proxy_pass http://127.0.0.1:{port};
            proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade; proxy_set_header Host $host;
            proxy_read_timeout 3600s; proxy_send_timeout 3600s;
            proxy_buffering off; proxy_socket_keepalive on;
        }}""")
            haproxy_acls_ws.append(f"    acl path_{core}_{proto}_{trans} path_beg {endpoint_path}\n    use_backend bk_nginx if path_{core}_{proto}_{trans}")
            
        elif proxy == "caddy":
            caddy_handles.append(f"""
    handle {endpoint_path}* {{
        reverse_proxy 127.0.0.1:{port} {{ flush_interval -1
            transport http {{ versions h1 h2c 2 }}
        }}
    }}""")
            haproxy_acls_caddy.append(f"    acl path_{core}_{proto}_{trans} path_beg {endpoint_path}\n    use_backend bk_caddy if path_{core}_{proto}_{trans}")
            
        elif proxy == "haproxy_direct":
            haproxy_acls_grpc.append(f"    acl path_{core}_{proto}_{trans} path_beg {endpoint_path}\n    use_backend bk_core_{port} if path_{core}_{proto}_{trans}")
            haproxy_backends.append(f"backend bk_core_{port}\n    server s1 127.0.0.1:{port} proto h2")

    # --- Write Fortress Config ---
    with open('/etc/fortress/whitelist.json', 'w') as f:
        json.dump({"allowed_prefixes": fortress_whitelist}, f)
        
    with open('/etc/fortress/bridges.json', 'w') as f:
        json.dump({"bridges": bridge_mapping}, f)

    # --- Write Xray Config ---
    xray_rules = [{"type": "field", "ip": ["geoip:private"], "outboundTag": "direct"}, {"type": "field", "port": "443", "network": "udp", "outboundTag": "block"}]
    if ads_mode == "normal":
        xray_rules.append({"type": "field", "domain": ["geosite:ads-normal"], "outboundTag": "block"})
    xray_rules.append({"type": "field", "inboundTag": [r["tag"] for r in xray_inbounds], "outboundTag": "direct"})
    
    with open('/etc/xray/config.json', 'w') as f:
        json.dump({"log": {"loglevel": "warning"}, "inbounds": xray_inbounds, "outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}], "routing": {"domainStrategy": "AsIs", "rules": xray_rules}}, f, indent=2)

    # --- Write Sing-box Config ---
    sb_rules = [{"action": "route", "ip_cidr": ["geoip:private"], "outbound": "direct"}, {"action": "route", "port": [443], "network": ["udp"], "outbound": "block"}]
    if ads_mode == "normal":
        sb_rules.append({"action": "route", "rule_set": ["geosite-ads"], "outbound": "block"})
    
    sb_route = {"rules": sb_rules, "auto_detect_interface": True}
    if ads_mode == "normal":
        sb_route["rule_set"] = [{"type": "local", "tag": "geosite-ads", "format": "binary", "path": "/usr/local/share/xray/geosite.dat"}]

    with open('/etc/singbox/config.json', 'w') as f:
        json.dump({"log": {"level": "warn"}, "inbounds": singbox_inbounds, "outbounds": [{"type": "direct", "tag": "direct"}, {"type": "block", "tag": "block"}], "route": sb_route}, f, indent=2)

    # --- Write Envoy Config ---
    envoy_yaml = {
        "static_resources": {
            "listeners": [{
                "name": "listener_0",
                "address": {"socket_address": {"address": "127.0.0.1", "port_value": 8081}},
                "filter_chains": [{"filters": [{
                    "name": "envoy.filters.network.http_connection_manager",
                    "typed_config": {
                        "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                        "stat_prefix": "ingress", "codec_type": "AUTO", "stream_idle_timeout": "0s",
                        "upgrade_configs": [{"upgrade_type": "websocket"}],
                        "route_config": {"name": "local_route", "virtual_hosts": [{"name": "backend", "domains": ["*"], "routes": [{"match": {"prefix": "/"}, "route": {"cluster": "haproxy", "timeout": "0s", "idle_timeout": "0s"}}]}]},
                        "http_filters": [{"name": "envoy.filters.http.router", "typed_config": {"@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"}}]
                    }
                }]}]
            }],
            "clusters": [{"name": "haproxy", "type": "STATIC", "connect_timeout": "1s", "load_assignment": {"cluster_name": "haproxy", "endpoints": [{"lb_endpoints": [{"endpoint": {"address": {"socket_address": {"address": "127.0.0.1", "port_value": 8082}}}}]}]}}]
        }
    }
    with open('/etc/envoy/envoy.yaml', 'w') as f:
        yaml.dump(envoy_yaml, f, default_flow_style=False)

    # --- Write HAProxy Config ---
    haproxy_cfg = f"""global
    maxconn 65535
    log stdout format raw local0
defaults
    mode http
    timeout connect 10s
    timeout client  3600s
    timeout server  3600s
    timeout tunnel  3600s
    option httplog
frontend main
    bind 127.0.0.1:8082
    acl is_health path /health
    http-request return status 200 content-type "text/plain" string "OK" if is_health
    
{"\n".join(haproxy_acls_grpc)}
{"\n".join(haproxy_acls_ws)}
{"\n".join(haproxy_acls_caddy)}

backend bk_nginx
    server s1 127.0.0.1:8083
backend bk_caddy
    server s1 127.0.0.1:8084
{"\n".join(haproxy_backends)}
"""
    with open('/etc/haproxy/haproxy.cfg', 'w') as f:
        f.write(haproxy_cfg)

    # --- Write Nginx Config ---
    nginx_cfg = f"""worker_processes auto;
worker_rlimit_nofile 16384;
events {{ worker_connections 4096; use epoll; multi_accept on; }}
http {{
    access_log off; sendfile on; tcp_nopush on; tcp_nodelay on;
    map $http_upgrade $connection_upgrade {{ default upgrade; '' close; }}
    server {{
        listen 8083 backlog=4096; server_name _;
{"\n".join(nginx_locations)}
        location = /health {{ return 200 "OK"; }}
        location / {{ return 404 "Not Found"; }}
    }}
}}"""
    with open('/etc/nginx/nginx.conf', 'w') as f:
        f.write(nginx_cfg)

    # --- Write Caddy Config ---
    caddy_cfg = f"""{{ admin off; auto_https off; servers {{ protocols h1 h2c }} }}
:8084 {{
    handle /health {{ respond "OK" 200 }}
{"\n".join(caddy_handles)}
    handle {{ respond "Not Found" 404 }}
}}"""
    with open('/etc/caddy/Caddyfile', 'w') as f:
        f.write(caddy_cfg)

    print("[RENDER] Configurations generated successfully.")

if __name__ == "__main__":
    generate_configs()
