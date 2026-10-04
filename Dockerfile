# ==============================================================================
# DOCKERFILE — Unified Multiplexed Relay Engine
# ==============================================================================
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV XRAY_VERSION="1.8.24"
ENV SINGBOX_VERSION="1.10.1"

# 1. Install System Packages, Envoy, Caddy, HAProxy, Nginx, Dropbear, OpenSSH, Python3, Supervisor, Netcat
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg ca-certificates python3 python3-yaml python3-uvloop supervisor \
    nginx haproxy netcat-openbsd debian-keyring debian-archive-keyring \
    apt-transport-https dropbear-bin openssh-server unzip \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list \
    && curl -fsSL https://apt.envoyproxy.io/signing.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/envoy.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/etc/apt/trusted.gpg.d/envoy.gpg] https://apt.envoyproxy.io bookworm main" > /etc/apt/sources.list.d/envoy.list \
    && apt-get update && apt-get install -y --no-install-recommends envoy caddy \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 2. Fetch and Install Xray-core
RUN curl -fsSL -o /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-64.zip" \
    && unzip -q /tmp/xray.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && rm -f /tmp/xray.zip

# 3. Fetch and Install Sing-box
RUN curl -fsSL -o /tmp/singbox.tar.gz "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/singbox.tar.gz -C /tmp/ \
    && mv /tmp/sing-box-${SINGBOX_VERSION}-linux-amd64/sing-box /usr/local/bin/ \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/singbox*

# 4. Download Geo Data (geoip.dat and geosite.dat from Gojo-Xlimit source)
RUN mkdir -p /usr/local/share/xray \
    && curl -fsSL -o /usr/local/share/xray/geoip.dat "https://github.com/gojo-xlimit/x-geosource/raw/main/geoip.dat" \
    && curl -fsSL -o /usr/local/share/xray/geosite.dat "https://github.com/gojo-xlimit/x-geosource/raw/main/output/geosite.dat"

# 5. Scaffold Directories and Permissions
RUN mkdir -p /etc/xray /etc/singbox /etc/envoy /etc/haproxy /etc/caddy /etc/nginx/conf.d \
    /etc/fortress /etc/dropbear /var/run/sshd /var/log/supervisor /run/nginx /app/custom-tools \
    && grep -qx '/bin/false' /etc/shells || echo '/bin/false' >> /etc/shells

COPY . /app
WORKDIR /app

RUN chmod +x /app/entrypoint.sh /app/relay/*.py /app/custom-tools/*.sh

EXPOSE 8080

# ==============================================================================
# HEALTHCHECK — For local Docker testing/diagnostics
# Uses Fortress/Nginx/Caddy /health endpoint to verify multiplexer state
# ==============================================================================
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
