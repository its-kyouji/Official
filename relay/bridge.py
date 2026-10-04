#!/usr/bin/env python3
# ==============================================================================
# BRIDGE.PY — HTTP-Upgrade to Raw TCP (With X-Sorcerer Optimizations)
# ==============================================================================

import asyncio
import base64
import hashlib
import json
import socket
import sys

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
BUF = 262144  # Tumaas sa 256KB mula sa X-Sorcerer para sa mas magandang speedtest burst
IDLE_TIMEOUT = 600

# ==============================================================================
# OS KERNEL SOCKET OPTIMIZATIONS
# ==============================================================================
def tune(writer):
    sock = writer.get_extra_info("socket")
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 15)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        except OSError: pass
        except AttributeError: pass

def switching_response(key):
    out = b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
    if key:
        digest = hashlib.sha1((key + WS_GUID.encode('ascii'))).digest()
        out += b"Sec-WebSocket-Accept: " + base64.b64encode(digest) + b"\r\n"
    return out + b"\r\n"

# ==============================================================================
# ASYNC RELAY PIPE (With Half-Close Logic)
# ==============================================================================
async def pipe(src, dst):
    try:
        while True:
            data = await asyncio.wait_for(src.read(BUF), timeout=IDLE_TIMEOUT)
            if not data or dst.is_closing(): break
            dst.write(data)
            await dst.drain()
    except asyncio.TimeoutError: pass
    except Exception: pass
    finally:
        # X-Sorcerer Half-Close Logic: allows the other leg to finish transferring
        try: dst.write_eof()
        except (OSError, AttributeError): dst.close()

# ==============================================================================
# CLIENT HANDLER
# ==============================================================================
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
        header_end = head.find(b"\r\n\r\n") + 4
        leftover = head[header_end:]

        for line in head[:header_end].split(b"\r\n")[1:]:
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

        if leftover:
            uwriter.write(leftover)
            await uwriter.drain()

        await asyncio.gather(pipe(creader, uwriter), pipe(ureader, cwriter), return_exceptions=True)
    except Exception: pass
    finally:
        for w in (cwriter, uwriter):
            if w:
                try: w.close()
                except: pass

# ==============================================================================
# SERVER INITIALIZATION
# ==============================================================================
async def start_server(json_path):
    try:
        with open(json_path, 'r') as f: cfg = json.load(f)
    except Exception: return

    port, thost, tport, label = cfg["listen_port"], cfg["target_host"], cfg["target_port"], cfg["label"]
    server = await asyncio.start_server(lambda r, w: handle_client(r, w, thost, tport), "127.0.0.1", port)
    print(f"[BRIDGE:{label}] Active on 127.0.0.1:{port} -> {thost}:{tport}")
    async with server: await server.serve_forever()

async def main():
    files = [sys.argv[1]] if len(sys.argv) > 1 else ['/app/relay/bridge-ssh.json', '/app/relay/bridge-ovpn.json']
    tasks = [asyncio.create_task(start_server(p)) for p in files]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError: pass
    asyncio.run(main())
