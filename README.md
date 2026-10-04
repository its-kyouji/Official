# Official Relay (by its-kyouji)

A heavily multiplexed, anti-DDoS, multi-core, and multi-proxy relay designed exclusively for Google Cloud Run. This architecture utilizes a deterministic "Proxy Tree" to strictly separate L4 shielding, L7 circuit breaking, path routing, and transport handling across multiple engines (Envoy, HAProxy, Nginx, Caddy, Xray, Sing-box).

## Cloud Run Deployment Settings
This image requires specific Cloud Run service configurations. Do not rely on defaults.
*   **Port:** `8080` (Single public ingress)
*   **Request Timeout:** `3600` (1 hour, necessary for long-lived WebSocket/gRPC streams)
*   **Concurrency:** `1000` (Allows heavy multiplexing on a single warm instance)
*   **Min Instances:** `1` (Required to prevent scale-to-zero restart loops and connection drops)
*   **Execution Environment:** `gen2` (For full network performance)
*   **CPU Allocation:** `--no-cpu-throttling` (Always-on CPU is mandatory for background proxy processing)

## Open Risks & Known Limitations
1.  **gRPC/h2c passthrough:** `PRI * HTTP/2.0` (h2c) is passed raw through `fortress.py` and Envoy. It is unverified if the GCP L7 Load Balancer will alter or drop this cleartext HTTP/2 preface before it reaches the container.
2.  **XHTTP via Caddy:** The `flush_interval -1` directive disables buffering in Caddy, but it is unverified if it fully accommodates Xray's XHTTP `stream-one` mode under Cloud Run's strict HTTP/1.1 downgrade constraints.
3.  **Resource Contention:** This container runs 5 proxies (Fortress, Envoy, HAProxy, Nginx, Caddy), 2 cores (Xray, Sing-box), and Python bridges on a shared vCPU. CPU throttling or out-of-memory (OOM) kills are possible under severe load if the Cloud Run instance tier is too low.
4.  **OVPN Relay Dependency:** The OpenVPN relay (`/saeka-ovpn`) requires an active, reachable remote VM (`OVPN_UPSTREAM`). Connection states tracked in `ws_bridge.py` will drop if the Cloud Run instance migrates or scales down.

## Environment Variables
*   `UUID`: The core authentication UUID (Auto-generated if left blank).
*   `PASSWORD`: Core password for Trojan/Shadowsocks.
*   `BASE_PATH`: Base path for endpoints (e.g., `/relay`).
*   `CUSTOM_IP`: Host/IP used in generated client links.
*   `ADS_MODE`: Set to `normal` for ad-blocking, `off` for direct routing.
*   `CORES`: Comma-separated (`xray`, `singbox`).
*   `SSH_STACK`: Set to `dropbear` or `openssh`.
*   `SSH_USERS_HASHED`: Pre-hashed SHA-512 crypt strings for SSH tunnel users.
*   `OVPN_UPSTREAM`: Target IP for the OpenVPN bridge.

## License
MIT License. Provided as-is.
