ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM ${BUILD_FROM}

WORKDIR /app
COPY server.py /app/server.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
