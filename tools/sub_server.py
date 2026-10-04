#!/usr/bin/env python3
# ==== SUB_SERVER.PY ====
# Lightweight HTTP server that dynamically generates subscription links
# and serves the offline vault panel. Runs internally, routed via Nginx.

import os
import json
import base64
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8085
VAULT_TPL = "/app/panel/vault.html"

class SubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        host = self.headers.get("Host", "localhost").split(":")[0]
        
        uuid = os.environ.get("UUID", "default-uuid")
        custom_ip = os.environ.get("CUSTOM_IP", host)
        base_path = os.environ.get("BASE_PATH", "/relay")

        if self.path.split("?")[0].rstrip("/") == "/vault":
            self.send_vault(host, uuid, base_path)
            return

        # Generate Sub Links (Using the Master Routes)
        sub_lines = []
        try:
            import yaml
            with open('/app/routes.yaml', 'r') as f:
                routes = yaml.safe_load(f).get('routes', [])
            
            for r in routes:
                if r['core'] == "xray" and r['protocol'] in ["vless", "vmess"]:
                    path = f"{base_path}-{r['core']}-{r['protocol']}-{r['transport']}"
                    enc_path = urllib.parse.quote(path, safe="")
                    uri = f"{r['protocol']}://{uuid}@{custom_ip}:443?encryption=none&security=tls&sni={host}&type={r['transport']}&host={host}&path={enc_path}#Kyouji-{r['protocol'].upper()}-{r['transport'].upper()}"
                    sub_lines.append(uri)
        except Exception:
            pass

        payload = "\n".join(sub_lines)
        b64_output = base64.b64encode(payload.encode("utf-8"))

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(b64_output)))
        self.end_headers()
        self.wfile.write(b64_output)

    def send_vault(self, host, uuid, base_path):
        try:
            with open(VAULT_TPL, "r", encoding="utf-8") as f:
                tpl = f.read()
            
            body = tpl.replace("UUID_PLACEHOLDER", uuid).replace("HOST_PLACEHOLDER", host).replace("PATH_PLACEHOLDER", base_path).encode("utf-8")
            
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="Official-Vault.html"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args): pass

if __name__ == "__main__":
    print(f"[SUB] Sub server active on 127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), SubHandler).serve_forever()
