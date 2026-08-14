ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3

WORKDIR /app
COPY server.py /app/server.py
COPY installed_client_inspector.py /app/installed_client_inspector.py
COPY patch_server.py /app/patch_server.py
RUN python3 /app/patch_server.py && rm /app/patch_server.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
