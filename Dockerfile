FROM python:3.10-slim

# Install WireGuard and necessary tools
# Use iptables-legacy for better compatibility in containers
RUN apt-get update && apt-get install -y \
    wireguard-tools \
    iptables \
    iproute2 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Set up entrypoint script
RUN chmod +x /app/entrypoint.sh

# Expose Web UI port and WireGuard port
EXPOSE 8080
EXPOSE 51820/udp

# Set env variables
ENV WG_PORT=51820
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/app/entrypoint.sh"]