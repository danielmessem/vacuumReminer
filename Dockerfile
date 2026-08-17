ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}
RUN apk add --no-cache python3
WORKDIR /app
COPY server_y1_v120.py /app/server.py
COPY run.sh /run.sh
RUN python3 -m py_compile /app/server.py && chmod a+x /run.sh
CMD ["/run.sh"]
