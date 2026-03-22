#!/bin/sh
set -e

# Generate htpasswd for Loki basic auth from env vars
LOKI_USER="${LOKI_AUTH_USER:-loki}"
LOKI_PASS="${LOKI_AUTH_PASSWORD:-changeme}"
printf '%s:%s\n' "$LOKI_USER" "$(openssl passwd -apr1 "$LOKI_PASS")" > /etc/nginx/.htpasswd

# Create Loki data directories
mkdir -p /loki/chunks /loki/rules /loki/compactor

# Inject target URL into Grafana dashboard JSON files
TARGET="${HEALTHCHECK_TARGET_URL:-http://localhost:8080}"
sed -i "s|__TARGET_URL__|${TARGET}|g" /etc/grafana/provisioning/dashboards/*.json

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
