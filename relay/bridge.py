#!/usr/bin/env python3
import asyncio
import os
import socket
import sys
import json
from email.utils import formatdate

BUF_SIZE = 262144
IDLE_TIMEOUT = 600
HANDSHAKE_TIMEOUT = 4.0

def optimize_socket(sock):
    if not sock: return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 15)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUF_SIZE)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUF_SIZE)
    except OSError: pass

async def relay(reader, writer, label=""):
    try:
        while True:
            data = await asyncio.wait_for(reader.read(BUF_SIZE), timeout=IDLE_TIMEOUT)
            if not data: break
            if writer.is_closing(): break
            writer.write(data)
            await asyncio.wait_for(writer.drain(), timeout=IDLE_TIMEOUT)
    except asyncio.TimeoutError:
        print(f"[BRIDGE:{label}] Idle timeout", flush=True)
    except Exception as e:
        print(f"[BRIDGE:{label}] Error: {type(e).__name__}: {e}", flush=True)
    finally:
        try:
            writer.write_eof()
        except (OSError, AttributeError):
            writer.close()

async def handle_client(client_reader, client_writer, cfg):
    label = cfg.get("label", "UNKNOWN")
    try:
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = await asyncio.wait_for(client_reader.read(4096), timeout=HANDSHAKE_TIMEOUT)
            if not chunk:
                client_writer.close(); return
            raw += chunk
            if len(raw) > 16384:
                client_writer.close(); return

        header_end = raw.index(b"\r\n\r\n") + 4
        leftover = raw[header_end:]

        if b"upgrade: websocket" in raw.lower() or b"upgrade: http/1.1" in raw.lower():
            date_str = formatdate(timeval=None, localtime=False, usegmt=True)
            client_writer.write(
                b"HTTP/1.1 101 Switching Protocols\r\n"
                b"Upgrade: websocket\r\n"
                b"Connection: keep-alive, Upgrade\r\n"
                b"Date: " + date_str.encode() + b"\r\n"
                b"Server: Google Frontend\r\n"
                b"\r\n"
            )
            await client_writer.drain()
        else:
            client_writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            return

    except Exception as e:
        print(f"[BRIDGE:{label}] Handshake fail: {e}", flush=True)
        client_writer.close()
        return

    try:
        ssh_reader, ssh_writer = await asyncio.open_connection(cfg["target_host"], cfg["target_port"], limit=BUF_SIZE)
    except Exception as e:
        print(f"[BRIDGE:{label}] Upstream fail {cfg['target_host']}:{cfg['target_port']}: {e}", flush=True)
        client_writer.close()
        return

    optimize_socket(client_writer.get_extra_info('socket'))
    optimize_socket(ssh_writer.get_extra_info('socket'))

    if leftover:
        ssh_writer.write(leftover)
        await ssh_writer.drain()

    await asyncio.gather(
        relay(client_reader, ssh_writer, label=f"client->{label}"),
        relay(ssh_reader, client_writer, label=f"{label}->client"),
        return_exceptions=True
    )

async def main():
    if len(sys.argv) < 2:
        print("[BRIDGE] FATAL: Missing JSON config path", flush=True)
        sys.exit(1)
        
    json_path = sys.argv[1]
    try:
        with open(json_path, 'r') as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"[BRIDGE] FATAL: bad config {json_path}: {e}", flush=True)
        sys.exit(1)
        
    if not cfg.get("target_host"):
        print(f"[BRIDGE:{cfg.get('label', '?')}] disabled (empty target_host)", flush=True)
        sys.exit(0)

    server = await asyncio.start_server(
        lambda r, w: handle_client(r, w, cfg), 
        "127.0.0.1", 
        cfg["listen_port"], 
        limit=BUF_SIZE
    )
    print(f"[BRIDGE:{cfg['label']}] Listening on 127.0.0.1:{cfg['listen_port']} -> {cfg['target_host']}:{cfg['target_port']}", flush=True)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    try:
        import uvloop
        uvloop.install()
    except ImportError: pass
    asyncio.run(main())
