#!/usr/bin/env python3
import asyncio
import gc
import json
import os
import socket
import time
from collections import defaultdict

# ==============================================================================
# CONFIGURATION
# ==============================================================================

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", "8080"))
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8081

BUF_SIZE = 131072
H2C_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"

# ==============================================================================
# RUNTIME CONFIGURATION
# ==============================================================================

try:
    with open("/run/cfg/relay/fortress.json", "r") as f:
        config = json.load(f)
except Exception:
    config = {}

BAN_THRESHOLD = int(config.get("ban_threshold", 150))
BAN_TIME = int(config.get("ban_time_seconds", 600))
MAX_CONNECTIONS = int(config.get("max_connections", 950))
HANDSHAKE_TIMEOUT = float(config.get("handshake_timeout", 4))
BACKEND_CONNECT_TIMEOUT = float(config.get("backend_connect_timeout", 10))
IDLE_TIMEOUT = float(config.get("idle_timeout", 600))

ALLOWED_PATHS = {
    p.encode() for p in config.get(
        "whitelist_paths",
        ["/", "/health", "/runtime.json"]
    )
}

BASE_PATH = os.environ.get("BASE_PATH", "/relay")
BASE_PREFIX = (BASE_PATH + "-").encode()

# ==============================================================================
# CONNECTION / BAN STATE
# ==============================================================================

IP_HITS = defaultdict(list)
BANNED_IPS = {}
ACTIVE_CONNECTIONS = 0

# ==============================================================================
# SOCKET OPTIMIZATION
# ==============================================================================

def optimize_socket(sock: socket.socket):
    if not sock:
        return

    options = [
        (socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),
        (socket.SOL_SOCKET, socket.SO_RCVBUF, BUF_SIZE),
        (socket.SOL_SOCKET, socket.SO_SNDBUF, BUF_SIZE),
        (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),
    ]

    for level, option, value in options:
        try:
            sock.setsockopt(level, option, value)
        except OSError:
            pass

    tcp_options = (
        ("TCP_KEEPIDLE", 15),
        ("TCP_KEEPINTVL", 10),
        ("TCP_KEEPCNT", 3),
    )

    for name, value in tcp_options:
        option = getattr(socket, name, None)
        if option is None:
            continue
        try:
            sock.setsockopt(socket.IPPROTO_TCP, option, value)
        except OSError:
            pass

# ==============================================================================
# CLIENT IP
# ==============================================================================

def get_client_ip(headers, fallback):
    for line in headers:
        if line.lower().startswith(b"x-forwarded-for:"):
            value = line.split(b":", 1)[1].split(b",", 1)[0].strip()
            if value:
                return value.decode("utf-8", "ignore")

    for line in headers:
        if line.lower().startswith(b"x-real-ip:"):
            value = line.split(b":", 1)[1].strip()
            if value:
                return value.decode("utf-8", "ignore")

    return fallback

# ==============================================================================
# IP BAN / RATE LIMIT
# ==============================================================================

def is_banned(ip):
    now = time.time()

    expiry = BANNED_IPS.get(ip)
    if expiry is not None:
        if now < expiry:
            return True
        del BANNED_IPS[ip]

    hits = IP_HITS[ip]
    IP_HITS[ip] = [t for t in hits if now - t < 60]
    IP_HITS[ip].append(now)

    if len(IP_HITS[ip]) > BAN_THRESHOLD:
        BANNED_IPS[ip] = now + BAN_TIME
        print(f"[FORTRESS] BANNED IP: {ip}", flush=True)
        return True

    return False

# ==============================================================================
# HTTP REQUEST VALIDATION
# ==============================================================================

def validate_request(raw):
    header_end = raw.find(b"\r\n\r\n")
    if header_end < 0:
        raise ValueError("Incomplete header")

    lines = raw[:header_end].split(b"\r\n")
    if not lines:
        raise ValueError("Malformed request")

    request_line = lines[0].split(b" ")
    if len(request_line) < 2:
        raise ValueError("Malformed request line")

    path = request_line[1].split(b"?", 1)[0]

    if path in ALLOWED_PATHS:
        return lines, path

    if path.startswith(BASE_PREFIX):
        return lines, path

    return lines, path

# ==============================================================================
# FULL-DUPLEX RELAY
# ==============================================================================

async def relay_stream(reader, writer):
    try:
        while True:
            data = await asyncio.wait_for(
                reader.read(BUF_SIZE),
                timeout=IDLE_TIMEOUT
            )

            if not data:
                break

            writer.write(data)
            await writer.drain()

    except asyncio.TimeoutError:
        pass
    except (ConnectionError, asyncio.IncompleteReadError):
        pass
    except Exception:
        pass
    finally:
        try:
            writer.write_eof()
        except Exception:
            pass

# ==============================================================================
# CLIENT HANDLER
# ==============================================================================

async def handle_client(reader, writer):
    global ACTIVE_CONNECTIONS

    peer = writer.get_extra_info("peername")
    raw_ip = peer[0] if peer else "127.0.0.1"
    client_ip = raw_ip

    if ACTIVE_CONNECTIONS >= MAX_CONNECTIONS:
        writer.close()
        await writer.wait_closed()
        return

    ACTIVE_CONNECTIONS += 1
    backend_writer = None

    try:
        optimize_socket(writer.get_extra_info("socket"))

        raw = b""

        while b"\r\n\r\n" not in raw:
            chunk = await asyncio.wait_for(
                reader.read(65536),
                timeout=HANDSHAKE_TIMEOUT
            )

            if not chunk:
                raise ValueError("Empty payload")

            raw += chunk

            if len(raw) > 16384:
                raise ValueError("Header too large")

        header_end = raw.find(b"\r\n\r\n")
        headers = raw[:header_end].split(b"\r\n")

        client_ip = get_client_ip(headers[1:], raw_ip)

        if is_banned(client_ip):
            writer.close()
            await writer.wait_closed()
            return

        if not raw.startswith(H2C_PREFACE):
            _, req_path = validate_request(raw)

            if (
                req_path not in ALLOWED_PATHS
                and not req_path.startswith(BASE_PREFIX)
            ):
                print(
                    f"[FORTRESS] Rejected Path: "
                    f"{req_path.decode(errors='ignore')} "
                    f"IP: {client_ip}",
                    flush=True
                )

                writer.write(
                    b"HTTP/1.1 403 Forbidden\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )
                await writer.drain()
                return

        # ======================================================================
        # BACKEND CONNECTION
        # ======================================================================

        try:
            _, backend_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    BACKEND_HOST,
                    BACKEND_PORT
                ),
                timeout=BACKEND_CONNECT_TIMEOUT
            )

            optimize_socket(
                backend_writer.get_extra_info("socket")
            )

        except Exception as exc:
            print(
                f"[FORTRESS] Backend unavailable: "
                f"{type(exc).__name__}: {exc}",
                flush=True
            )
            return

        # ======================================================================
        # PRESERVE INITIAL PAYLOAD
        # ======================================================================

        backend_writer.write(raw)
        await backend_writer.drain()

        # ======================================================================
        # FULL-DUPLEX STREAMING
        # ======================================================================

        await asyncio.gather(
            relay_stream(reader, backend_writer),
            relay_stream(
                await asyncio.open_connection(
                    BACKEND_HOST,
                    BACKEND_PORT
                )[0] if False else reader,
                writer
            ),
            return_exceptions=True
        )

    except asyncio.TimeoutError:
        print(
            f"[FORTRESS] Handshake timeout: {client_ip}",
            flush=True
        )

    except ValueError as exc:
        print(
            f"[FORTRESS] Dropped: {type(exc).__name__}: {exc}",
            flush=True
        )

    except Exception as exc:
        print(
            f"[FORTRESS] Error: {type(exc).__name__}: {exc}",
            flush=True
        )

    finally:
        ACTIVE_CONNECTIONS -= 1

        if backend_writer is not None:
            try:
                backend_writer.close()
                await backend_writer.wait_closed()
            except Exception:
                pass

        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

# ==============================================================================
# SERVER
# ==============================================================================

async def main():
    server = await asyncio.start_server(
        handle_client,
        LISTEN_HOST,
        LISTEN_PORT,
        limit=BUF_SIZE,
        backlog=1024
    )

    print(
        f"[FORTRESS] Shield Active on port {LISTEN_PORT} "
        f"-> forwarding to Envoy {BACKEND_PORT}",
        flush=True
    )

    async with server:
        await server.serve_forever()

# ==============================================================================
# ENTRYPOINT
# ==============================================================================

if __name__ == "__main__":
    gc.set_threshold(50_000, 500, 100)

    try:
        import uvloop
        asyncio.set_event_loop_policy(
            uvloop.EventLoopPolicy()
        )
    except ImportError:
        pass

    asyncio.run(main())
