ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 docker-cli

WORKDIR /app
COPY server_y1_v132.py /app/server.py

RUN python3 -m py_compile /app/server.py

CMD ["python3", "/app/server.py"]
