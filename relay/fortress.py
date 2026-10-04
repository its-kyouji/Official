#!/usr/bin/env python3
# ==============================================================================
# ANTI-DDOS FORTRESS (L4/L7 Shield)
# Edge proxy on public port (8080) -> Envoy -> HAProxy -> Nginx/Caddy/Xray
# ==============================================================================

import asyncio
import socket
import os

# ==============================================================================
# CONSTANTS & CONFIGURATION
# ==============================================================================
LISTEN_PORT = int(os.environ.get("PORT", "8080"))
BACKEND_PORT = 8081  # Envoy Circuit Breaker
BUF_SIZE = 131072
H2C_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

# Valid paths to pass through; anything else gets 403 Forbidden
ALLOWED_PREFIXES = [b"/health", b"/relay"]

# ==============================================================================
# SOCKET OPTIMIZATION
# ==============================================================================
def optimize_socket(sock: socket.socket):
    if not sock: return
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, BUF_SIZE)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, BUF_SIZE)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    except OSError: pass

# ==============================================================================
# CONNECTION HANDLER
# ==============================================================================
async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    try:
        # Anti-Slowloris: 3-second strict timeout for initial read
        chunk = await asyncio.wait_for(reader.read(65536), timeout=3.0)
        if not chunk: raise ValueError("Empty")

        # Allow raw gRPC/HTTP2 preface bypass
        if chunk.startswith(H2C_PREFACE):
            raw = chunk
        else:
            raw = chunk
            # Accumulate headers until \r\n\r\n
            while b"\r\n\r\n" not in raw:
                more = await asyncio.wait_for(reader.read(65536), timeout=2.0)
                if not more: raise ValueError("Incomplete")
                raw += more
                if len(raw) > 16384: raise ValueError("Oversized")

            # Fast-drop path validation
            header_end = raw.find(b"\r\n\r\n")
            lines = raw[:header_end].split(b"\r\n")
            req_line = lines[0].split(b" ")
            if len(req_line) < 2: raise ValueError("Malformed")
            
            base_path = req_line[1].split(b"?")[0]
            if base_path != b"/" and not any(base_path.startswith(p) for p in ALLOWED_PREFIXES):
                writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await writer.drain(); writer.close(); return

        # Forward clean traffic to backend
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

    except Exception: pass
    finally: writer.close()

# ==============================================================================
# SERVER INITIALIZATION
# ==============================================================================
async def main():
    server = await asyncio.start_server(handle_client, "0.0.0.0", LISTEN_PORT)
    async with server: await server.serve_forever()

if __name__ == "__main__":
    import gc
    import uvloop
    
    # GC Tuning from Gojo-Relay for long-lived Cloud Run instances
    gc.set_threshold(50_000, 500, 100)
    
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    asyncio.run(main())
