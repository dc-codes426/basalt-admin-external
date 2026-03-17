FROM grafana/grafana:11.5.2 AS grafana

FROM grafana/loki:3.4.2 AS loki

FROM debian:bookworm-slim

# Install supervisor and nginx
RUN apt-get update && \
    apt-get install -y supervisor nginx openssl && \
    rm -rf /var/lib/apt/lists/*

# Copy Loki binary
COPY --from=loki /usr/bin/loki /usr/bin/loki

# Copy Grafana
COPY --from=grafana /usr/share/grafana /usr/share/grafana
COPY --from=grafana /run.sh /run.sh
RUN chmod +x /run.sh

# Grafana needs these paths
ENV GF_PATHS_HOME=/usr/share/grafana
ENV GF_PATHS_DATA=/var/lib/grafana
ENV GF_PATHS_LOGS=/var/log/grafana
ENV GF_PATHS_PLUGINS=/var/lib/grafana/plugins
ENV GF_PATHS_PROVISIONING=/etc/grafana/provisioning
ENV PATH=/usr/share/grafana/bin:$PATH

RUN mkdir -p /var/lib/grafana /var/log/grafana /etc/grafana/provisioning/datasources /etc/grafana/provisioning/dashboards /etc/nginx

# Loki config
COPY loki/loki-config.yaml /etc/loki/loki-config.yaml

# Grafana provisioning — auto-configure Loki datasource + dashboards
COPY grafana/provisioning/datasources/loki.yml /etc/grafana/provisioning/datasources/loki.yml
COPY grafana/provisioning/dashboards/dashboards.yml /etc/grafana/provisioning/dashboards/dashboards.yml
COPY grafana/provisioning/dashboards/vultiserver.json /etc/grafana/provisioning/dashboards/vultiserver.json

# Supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Nginx config (basic auth proxy for Loki)
COPY nginx.conf /etc/nginx/nginx.conf

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Default env vars
ENV GRAFANA_ADMIN_USER=admin
ENV GRAFANA_ADMIN_PASSWORD=admin
ENV LOKI_AUTH_USER=loki
ENV LOKI_AUTH_PASSWORD=changeme
ENV GF_SERVER_ROOT_URL=http://localhost:3000/

# Port 3000 = Grafana, Port 3100 = Loki push API (behind basic auth)
EXPOSE 3000 3100

ENTRYPOINT ["/entrypoint.sh"]
