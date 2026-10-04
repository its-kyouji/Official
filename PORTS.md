# Port Allocation Map

*   **Public Edge Port:** `$PORT` (Injected by Cloud Run, defaults to `8080`)
*   **Fortress L4 Shield:** `8080` (Binds $PORT directly)
*   **Envoy Circuit Breaker:** `8081`
*   **HAProxy Master Router:** `8082`
*   **Nginx (WS lanes + Panel):** `8083`
*   **Caddy (XHTTP lanes):** `8084`
*   **Sub Server & Vault API:** `8085`
*   **Xray Inbounds:** `10001 - 10016`
*   **Sing-box Inbounds:** `11001 - 11012`
*   **Dropbear SSH Backend:** `2200`
*   **OpenSSH Backend:** `2201`
*   **BadVPN UDPGW:** `7300`
*   **Bridge SSH:** `2222`
*   **Bridge OVPN:** `2223`
*   **Cert Server (/cert):** `2224`
