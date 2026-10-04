#!/usr/bin/env python3
# ==== BRIDGE.PY ====
# Unified HTTP-Upgrade to raw TCP bridge for SSH and OpenVPN.

import asyncio
import base64
import hashlib
import json
import socket
import sys

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BUF = 65536

def tune(writer):
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except OSError: pass

def switching_response(key):
    out = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
    if key:
        digest = hashlib.sha1((key + WS_GUID.encode('ascii'))).digest()
        out += b"Sec-WebSocket-Accept: " + base64.b64encode(digest) + b"\r\n"
    return out + b"\r\n"

async def pipe(src, dst):
    try:
        while True:
            data = await src.read(BUF)
            if not data: break
            dst.write(data); await dst.drain()
    except Exception: pass
    finally:
        try: dst.close()
        except: pass

async def handle_client(creader, cwriter, target_host, target_port):
    uwriter = None
    try:
        tune(cwriter)
        head = bytearray()
        while b"\r\n\r\n" not in head:
            chunk = await asyncio.wait_for(creader.read(4096), timeout=10)
            if not chunk: return
            head.extend(chunk)
            if len(head) > 65536: return
        
        headers = {}
        for line in head.split(b"\r\n")[1:]:
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().lower()] = v.strip()
                
        if b"upgrade" not in headers:
            cwriter.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await cwriter.drain(); cwriter.close(); return

        ureader, uwriter = await asyncio.wait_for(asyncio.open_connection(target_host, target_port), timeout=10)
        tune(uwriter)

        cwriter.write(switching_response(headers.get(b"sec-websocket-key", b"")))
        await cwriter.drain()

        await asyncio.gather(pipe(creader, uwriter), pipe(ureader, cwriter), return_exceptions=True)
    except Exception:
        pass
    finally:
        for w in (cwriter, uwriter):
            if w:
                try: w.close()
                except: pass

async def start_server(json_path):
    try:
        with open(json_path, 'r') as f:
            cfg = json.load(f)
    except Exception:
        return

    port = cfg["listen_port"]
    thost = cfg["target_host"]
    tport = cfg["target_port"]
    label = cfg["label"]

    server = await asyncio.start_server(lambda r, w: handle_client(r, w, thost, tport), "127.0.0.1", port)
    print(f"[BRIDGE:{label}] Active on 127.0.0.1:{port} -> {thost}:{tport}")
    async with server: await server.serve_forever()

async def main():
    files = [sys.argv[1]] if len(sys.argv) > 1 else ['/app/relay/bridge-ssh.json', '/app/relay/bridge-ovpn.json']
    tasks = [asyncio.create_task(start_server(p)) for p in files]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
