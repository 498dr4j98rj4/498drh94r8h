FROM python:3.10-slim

# Install WireGuard tools, userspace implementation, and networking utilities
RUN apt-get update && apt-get install -y \
    wireguard-tools \
    wireguard-go \
    iptables \
    iproute2 \
    procps \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh

EXPOSE 8080
EXPOSE 51820/udp

ENV WG_PORT=51820
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/app/entrypoint.sh"]