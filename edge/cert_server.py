#!/usr/bin/env python3
# ==== CERT_SERVER.PY ====
# Secured provisioning server for OpenVPN profiles. Returns 404 unless queried
# at /cert with valid Basic Auth utilizing the SSH_USERS_HASHED environment.

import base64
import hmac
import os
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 2224

def load_users():
    raw_hashed = os.environ.get("SSH_USERS_HASHED", "")
    users = {}
    for pair in raw_hashed.split(","):
        user, separator, encoded = pair.strip().partition(":")
        if separator and user and encoded.startswith("$6$"):
            users[user] = encoded
    return users

def check_auth(header, users):
    if not header or not header.startswith("Basic "): return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        user, separator, password = decoded.partition(":")
    except Exception: return False
    if not separator: return False

    ok = False
    for expected_user, expected_password in users.items():
        if expected_password.startswith("$6$"):
            salt = expected_password.split("$", 3)[2]
            try:
                result = subprocess.run(
                    ["openssl", "passwd", "-6", "-salt", salt, "-stdin"],
                    input=password, text=True, capture_output=True, timeout=2, check=True,
                ).stdout.strip()
            except Exception: result = ""
            password_ok = hmac.compare_digest(result, expected_password)
        else:
            password_ok = False
        ok |= hmac.compare_digest(expected_user, user) and password_ok
    return ok

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/cert":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"404 Not Found\n")
            return

        users = load_users()
        if not users:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b"No users configured - /cert locked.\n")
            return

        if not check_auth(self.headers.get("Authorization"), users):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="VPN profile", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(b"Login required.\n")
            return
            
        profile_b64 = os.environ.get("OVPN_PROFILE_B64", "")
        if not profile_b64:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Profile not provisioned in environment.\n")
            return

        try:
            cert_data = base64.b64decode(profile_b64, validate=True)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", 'attachment; filename="client.ovpn"')
            self.send_header("Content-Length", str(len(cert_data)))
            self.end_headers()
            self.wfile.write(cert_data)
        except Exception:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Failed to decode profile.\n")

    def log_message(self, format, *args): pass

if __name__ == "__main__":
    print("[CERT] Server active on 127.0.0.1:2224")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
