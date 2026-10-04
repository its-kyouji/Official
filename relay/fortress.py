#!/usr/bin/env python3
# ==== FORTRESS.PY ====
# L4/L7 Asynchronous Shield. Intercepts Cloud Run $PORT (8080).
# Validates path whitelists, drops malicious headers, and passes h2c raw.

import asyncio
import json
import os
import socket
import uvloop

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

LISTEN_PORT = int(os.environ.get("PORT", "8080"))
BACKEND_PORT = 8081  # Envoy
BUF_SIZE = 131072
BANNED_IPS = set()
H2C_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

def load_whitelist():
    try:
        with open('/etc/fortress/whitelist.json', 'r') as f:
            return [p.encode() for p in json.load(f)["allowed_prefixes"]]
    except Exception:
        return [b"/health"]

ALLOWED_PREFIXES = load_whitelist()

def get_real_ip(headers_bytes, raw_ip):
    for line in headers_bytes:
        if line.lower().startswith(b"x-forwarded-for:"):
            return line.split(b":", 1)[1].split(b",")[0].strip().decode('utf-8', 'ignore')
    return raw_ip

def optimize_socket(sock: socket.socket):
    if not sock: return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError: pass

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer = writer.get_extra_info("peername")
    raw_socket_ip = peer[0] if peer else "127.0.0.1"

    try:
        chunk = await asyncio.wait_for(reader.read(65536), timeout=3.0)
        if not chunk: raise ValueError("Empty")

        if chunk.startswith(H2C_PREFACE):
            raw = chunk
        else:
            raw = chunk
            while b"\r\n\r\n" not in raw:
                more = await asyncio.wait_for(reader.read(65536), timeout=2.0)
                if not more: raise ValueError("Incomplete")
                raw += more
                if len(raw) > 16384: raise ValueError("Oversized")

            header_end = raw.find(b"\r\n\r\n")
            lines = raw[:header_end].split(b"\r\n")
            client_ip = get_real_ip(lines[1:], raw_socket_ip)

            if client_ip in BANNED_IPS:
                writer.close(); return

            req_line = lines[0].split(b" ")
            if len(req_line) < 2: raise ValueError("Malformed")
            
            base_path = req_line[1].split(b"?")[0]
            
            if base_path != b"/" and not any(base_path.startswith(p) for p in ALLOWED_PREFIXES):
                BANNED_IPS.add(client_ip)
                writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await writer.drain(); writer.close(); return

        b_reader, b_writer = await asyncio.open_connection("127.0.0.1", BACKEND_PORT)
        optimize_socket(b_writer.get_extra_info("socket"))
        optimize_socket(writer.get_extra_info("socket"))

        b_writer.write(raw)
        await b_writer.drain()

        async def relay(src, dst):
            try:
                while True:
                    data = await src.read(BUF_SIZE)
                    if not data: break
                    dst.write(data); await dst.drain()
            except Exception: pass
            finally: dst.close()

        await asyncio.gather(relay(reader, b_writer), relay(b_reader, writer), return_exceptions=True)

    except Exception:
        pass
    finally:
        writer.close()

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", LISTEN_PORT)
    print(f"[FORTRESS] L4 shield active on 0.0.0.0:{LISTEN_PORT}")
    async with server: await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
