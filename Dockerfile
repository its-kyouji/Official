# ==============================================================================
# DOCKERFILE — Unified Multiplexed Relay Engine (Kyouji + X-Sorcerer Hybrid)
# ==============================================================================
FROM debian:bookworm-slim AS builder

ENV DEBIAN_FRONTEND=noninteractive

# ==============================================================================
# 1. Install Build Dependencies
# ==============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential wget bzip2 cmake git libssl-dev zlib1g-dev ca-certificates

# ==============================================================================
# 2. Build Dropbear with OpenSSH Spoofing
# ==============================================================================
RUN wget https://matt.ucc.asn.au/dropbear/releases/dropbear-2024.85.tar.bz2 && \
    tar -xf dropbear-2024.85.tar.bz2 && \
    cd dropbear-2024.85 && \
    grep -rl "SSH-2.0-dropbear_" . | xargs sed -i 's/SSH-2.0-dropbear_/SSH-2.0-/g' && \
    echo '#define DROPBEAR_VERSION "OpenSSH_10.2p1 Ubuntu-2ubuntu3.6"' > localoptions.h && \
    ./configure && \
    make PROGRAMS="dropbear dropbearkey" && \
    make PROGRAMS="dropbear dropbearkey" install

# ==============================================================================
# 3. Build BadVPN UDPGW
# ==============================================================================
RUN git clone --depth 1 https://github.com/ambrop72/badvpn.git /tmp/badvpn && \
    mkdir -p /tmp/badvpn/build && \
    cd /tmp/badvpn/build && \
    cmake .. -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 && \
    make install

# ==============================================================================
# MAIN IMAGE CONTEXT
# ==============================================================================
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV XRAY_VERSION="1.8.24"
ENV SINGBOX_VERSION="1.10.1"

# ==============================================================================
# 4. Copy Compiled Binaries from Builder
# ==============================================================================
COPY --from=builder /usr/local/sbin/dropbear /usr/local/sbin/dropbear
COPY --from=builder /usr/local/bin/dropbearkey /usr/local/bin/dropbearkey
COPY --from=builder /usr/local/bin/badvpn-udpgw /usr/local/bin/badvpn-udpgw

# ==============================================================================
# 5. Install Runtime Dependencies (Proxies, Python, SSH)
# ==============================================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl gnupg ca-certificates python3 python3-yaml python3-uvloop supervisor \
    nginx haproxy netcat-openbsd debian-keyring debian-archive-keyring \
    apt-transport-https openssh-server unzip \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list \
    && curl -fsSL https://apt.envoyproxy.io/signing.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/envoy.gpg \
    && echo "deb [arch=amd64,arm64 signed-by=/etc/apt/trusted.gpg.d/envoy.gpg] https://apt.envoyproxy.io bookworm main" > /etc/apt/sources.list.d/envoy.list \
    && apt-get update && apt-get install -y --no-install-recommends envoy caddy \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# ==============================================================================
# 6. Fetch and Install Xray-core
# ==============================================================================
RUN curl -fsSL -o /tmp/xray.zip "https://github.com/XTLS/Xray-core/releases/download/v${XRAY_VERSION}/Xray-linux-64.zip" \
    && unzip -q /tmp/xray.zip -d /usr/local/bin/ \
    && chmod +x /usr/local/bin/xray \
    && rm -f /tmp/xray.zip

# ==============================================================================
# 7. Fetch and Install Sing-box
# ==============================================================================
RUN curl -fsSL -o /tmp/singbox.tar.gz "https://github.com/SagerNet/sing-box/releases/download/v${SINGBOX_VERSION}/sing-box-${SINGBOX_VERSION}-linux-amd64.tar.gz" \
    && tar -xzf /tmp/singbox.tar.gz -C /tmp/ \
    && mv /tmp/sing-box-${SINGBOX_VERSION}-linux-amd64/sing-box /usr/local/bin/ \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf /tmp/singbox*

# ==============================================================================
# 8. Download Geo Data (Gojo-Xlimit Custom Build)
# ==============================================================================
RUN mkdir -p /usr/local/share/xray \
    && curl -fsSL -o /usr/local/share/xray/geoip.dat "https://github.com/gojo-xlimit/x-geosource/raw/main/geoip.dat" \
    && curl -fsSL -o /usr/local/share/xray/geosite.dat "https://github.com/gojo-xlimit/x-geosource/raw/main/output/geosite.dat"

# ==============================================================================
# 9. Scaffold Directories and Permissions
# ==============================================================================
RUN mkdir -p /etc/xray /etc/singbox /etc/envoy /etc/haproxy /etc/caddy /etc/nginx/conf.d \
    /etc/fortress /etc/dropbear /var/run/sshd /var/log/supervisor /run/nginx /app/custom-tools \
    && grep -qx '/bin/false' /etc/shells || echo '/bin/false' >> /etc/shells

# ==============================================================================
# 10. Copy Application Files & Setup
# ==============================================================================
COPY . /app
WORKDIR /app

RUN chmod +x /app/entrypoint.sh /app/relay/*.py /app/custom-tools/*.sh

EXPOSE 8080

# ==============================================================================
# 11. Healthcheck (For local testing & diagnostics)
# ==============================================================================
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
