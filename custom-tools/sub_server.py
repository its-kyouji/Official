#!/usr/bin/env python3
import http.server
import socketserver
PORT = 8086
class SubHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Subscription Active")
with socketserver.TCPServer(("", PORT), SubHandler) as httpd:
    print(f"Sub server listening on port {PORT}")
    httpd.serve_forever()
