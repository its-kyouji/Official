#!/usr/bin/env python3

import asyncio
import socket
import os
import json
import time
from collections import defaultdict


# =================
# CONFIGURATION
# =================

LISTEN_PORT = int(os.environ.get("PORT", "8080"))
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8081

BUF_SIZE = 131072
HEADER_LIMIT = 16384
HEADER_TIMEOUT = 3.0
READ_TIMEOUT = 2.0
BACKEND_TIMEOUT = 10.0

H2C_PREFACE = b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n"
BASE_PREFIX = b"__BASE_PATH__-"


# =================
# FORTRESS POLICY
# =================

try:
    with open("/run/cfg/relay/fortress.json", "r") as f:
        config = json.load(f)
except Exception:
    config = {
        "ban_threshold": 150,
        "ban_time_seconds": 600,
        "whitelist_paths": [
            "/",
            "/health",
            "/runtime.json"
        ]
    }

BAN_THRESHOLD = int(config.get("ban_threshold", 150))
BAN_TIME = int(config.get("ban_time_seconds", 600))

ALLOWED_PATHS = {
    p.encode()
    for p in config.get(
        "whitelist_paths",
        ["/", "/health", "/runtime.json"]
    )
}

IP_HITS = defaultdict(list)
BANNED_IPS = {}


# =================
# CLIENT IP RESOLUTION
# =================

def get_client_ip(lines, fallback):
    for line in lines:
        if line.lower().startswith(b"x-forwarded-for:"):
            value = line.split(b":", 1)[1].strip()

            if value:
                return value.split(b",", 1)[0].strip().decode(
                    "utf-8",
                    "ignore"
                )

    return fallback


# =================
# SOCKET OPTIMIZATION
# =================

def optimize_socket(sock: socket.socket):
    if not sock:
        return

    try:
        sock.setsockopt(
            socket.IPPROTO_TCP,
            socket.TCP_NODELAY,
            1
        )
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_RCVBUF,
            BUF_SIZE
        )
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_SNDBUF,
            BUF_SIZE
        )
        sock.setsockopt(
            socket.SOL_SOCKET,
            socket.SO_KEEPALIVE,
            1
        )
    except OSError:
        pass


# =================
# IP RATE LIMITING
# =================

def is_banned(ip):
    now = time.time()

    expiry = BANNED_IPS.get(ip)

    if expiry is not None:
        if now >= expiry:
            del BANNED_IPS[ip]
        else:
            return True

    hits = IP_HITS[ip]

    IP_HITS[ip] = [
        timestamp
        for timestamp in hits
        if now - timestamp < 60
    ]

    IP_HITS[ip].append(now)

    if len(IP_HITS[ip]) > BAN_THRESHOLD:
        BANNED_IPS[ip] = now + BAN_TIME

        print(
            f"[FORTRESS] BANNED IP: {ip}",
            flush=True
        )

        return True

    return False


# =================
# BIDIRECTIONAL RELAY
# =================

async def relay_stream(src, dst):
    try:
        while True:
            data = await src.read(BUF_SIZE)

            if not data:
                break

            dst.write(data)
            await dst.drain()

    except (ConnectionError, asyncio.CancelledError):
        pass

    except Exception:
        pass


# =================
# CLIENT CONNECTION HANDLER
# =================

async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername")
    fallback_ip = peer[0] if peer else "127.0.0.1"

    client_ip = fallback_ip
    backend_reader = None
    backend_writer = None

    try:
        raw = await asyncio.wait_for(
            reader.read(65536),
            timeout=HEADER_TIMEOUT
        )

        if not raw:
            raise ValueError("Empty payload")

        # =================
        # H2C CONNECTION
        # =================

        if raw.startswith(H2C_PREFACE):
            client_ip = fallback_ip

        # =================
        # HTTP CONNECTION
        # =================

        else:
            while b"\r\n\r\n" not in raw:
                more = await asyncio.wait_for(
                    reader.read(65536),
                    timeout=READ_TIMEOUT
                )

                if not more:
                    raise ValueError("Incomplete header")

                raw += more

                if len(raw) > HEADER_LIMIT:
                    raise ValueError("Header too large")

            header_end = raw.find(b"\r\n\r\n")
            lines = raw[:header_end].split(b"\r\n")

            if not lines:
                raise ValueError("Malformed request")

            # =================
            # CLIENT IP
            # =================

            client_ip = get_client_ip(
                lines[1:],
                fallback_ip
            )

            if is_banned(client_ip):
                writer.close()
                return

            # =================
            # PATH VALIDATION
            # =================

            request_line = lines[0].split(b" ")

            if len(request_line) < 2:
                raise ValueError("Malformed request line")

            request_path = request_line[1].split(b"?", 1)[0]

            valid_path = (
                request_path in ALLOWED_PATHS
                or request_path.startswith(BASE_PREFIX)
            )

            if not valid_path:
                print(
                    "[FORTRESS] Rejected Path: "
                    f"{request_path.decode(errors='ignore')} "
                    f"IP={client_ip}",
                    flush=True
                )

                writer.write(
                    b"HTTP/1.1 403 Forbidden\r\n"
                    b"Connection: close\r\n"
                    b"\r\n"
                )

                await writer.drain()
                writer.close()
                return

        # =================
        # BACKEND CONNECTION
        # =================

        backend_reader, backend_writer = await asyncio.wait_for(
            asyncio.open_connection(
                BACKEND_HOST,
                BACKEND_PORT
            ),
            timeout=BACKEND_TIMEOUT
        )

        optimize_socket(
            writer.get_extra_info("socket")
        )

        optimize_socket(
            backend_writer.get_extra_info("socket")
        )

        backend_writer.write(raw)
        await backend_writer.drain()

        # =================
        # FULL-DUPLEX RELAY
        # =================

        await asyncio.gather(
            relay_stream(reader, backend_writer),
            relay_stream(backend_reader, writer),
            return_exceptions=True
        )

    except asyncio.TimeoutError:
        print(
            f"[FORTRESS] Timeout IP={client_ip}",
            flush=True
        )

    except Exception as e:
        print(
            f"[FORTRESS] Dropped "
            f"IP={client_ip} "
            f"ERR={type(e).__name__}: {e}",
            flush=True
        )

    finally:
        if backend_writer:
            backend_writer.close()

        writer.close()


# =================
# FORTRESS SERVER
# =================

async def main():
    server = await asyncio.start_server(
        handle_client,
        "0.0.0.0",
        LISTEN_PORT,
        limit=BUF_SIZE,
        backlog=1024
    )

    print(
        f"[FORTRESS] Shield Active "
        f"{LISTEN_PORT} -> {BACKEND_HOST}:{BACKEND_PORT}",
        flush=True
    )

    async with server:
        await server.serve_forever()


# =================
# APPLICATION ENTRYPOINT
# =================

if __name__ == "__main__":
    import gc

    gc.set_threshold(
        50_000,
        500,
        100
    )

    try:
        import uvloop

        asyncio.set_event_loop_policy(
            uvloop.EventLoopPolicy()
        )

    except ImportError:
        pass

    asyncio.run(main())
