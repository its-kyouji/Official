#!/usr/bin/env python3
import asyncio
import socket
import os
import json
import time
from collections import defaultdict

LISTEN_PORT = int(os.environ.get("PORT", "8080"))
BACKEND_PORT = 8081  # Points to Envoy
BUF_SIZE = 131072
H2C_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

# Injected safely via sed in entrypoint
BASE_PREFIX = b"__BASE_PATH__-"

try:
    with open("/run/cfg/relay/fortress.json", "r") as f:
        config = json.load(f)
except:
    config = {"ban_threshold": 150, "ban_time_seconds": 600, "whitelist_paths": ["/", "/health", "/runtime.json"]}

ALLOWED_PATHS = [p.encode() for p in config.get("whitelist_paths", [])]
IP_HITS = defaultdict(list)
BANNED_IPS = {}

def optimize_socket(sock: socket.socket):
    if not sock: return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUF_SIZE)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUF_SIZE)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError: pass

def is_banned(ip):
    now = time.time()
    if ip in BANNED_IPS:
        if now > BANNED_IPS[ip]:
            del BANNED_IPS[ip]
            return False
        return True
    
    IP_HITS[ip] = [t for t in IP_HITS[ip] if now - t < 60]
    IP_HITS[ip].append(now)
    if len(IP_HITS[ip]) > config["ban_threshold"]:
        BANNED_IPS[ip] = now + config["ban_time_seconds"]
        print(f"[FORTRESS] BANNED IP: {ip}", flush=True)
        return True
    return False

async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    peer_ip = writer.get_extra_info('peername')[0]
    if is_banned(peer_ip):
        writer.close(); return

    try:
        chunk = await asyncio.wait_for(reader.read(65536), timeout=3.0)
        if not chunk: raise ValueError("Empty payload")

        if chunk.startswith(H2C_PREFACE):
            raw = chunk
        else:
            raw = chunk
            while b"\r\n\r\n" not in raw:
                more = await asyncio.wait_for(reader.read(65536), timeout=2.0)
                if not more: raise ValueError("Incomplete header")
                raw += more
                if len(raw) > 16384: raise ValueError("Header too large")

            header_end = raw.find(b"\r\n\r\n")
            lines = raw[:header_end].split(b"\r\n")
            req_line = lines[0].split(b" ")
            if len(req_line) < 2: raise ValueError("Malformed request line")
            
            req_path = req_line[1].split(b"?")[0]
            
            # Allow logic
            is_valid = False
            if req_path in ALLOWED_PATHS:
                is_valid = True
            elif BASE_PREFIX in req_path:
                is_valid = True
                
            if not is_valid:
                print(f"[FORTRESS] Rejected Path: {req_path.decode(errors='ignore')}", flush=True)
                writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await writer.drain(); writer.close(); return

        b_reader, b_writer = await asyncio.open_connection("127.0.0.1", BACKEND_PORT)
        optimize_socket(b_writer.get_extra_info("socket"))
        optimize_socket(writer.get_extra_info("socket"))

        b_writer.write(raw)
        await b_writer.drain()

        async def pump(src, dst):
            try:
                while True:
                    data = await src.read(BUF_SIZE)
                    if not data: break
                    dst.write(data); await dst.drain()
            except Exception: pass
            finally: dst.close()

        await asyncio.gather(pump(reader, b_writer), pump(b_reader, writer), return_exceptions=True)

    except Exception as e:
        print(f"[FORTRESS] Dropped: {type(e).__name__}: {e}", flush=True)
    finally:
        writer.close()

async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", LISTEN_PORT)
    print(f"[FORTRESS] Shield Active on port {LISTEN_PORT} -> forwarding to Envoy 8081", flush=True)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    import gc
    gc.set_threshold(50_000, 500, 100)
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError: pass
    asyncio.run(main())
