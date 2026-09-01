ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 docker-cli

WORKDIR /app
COPY server_y1_v160.py /app/server.py
COPY cqyi87_profile.py /app/cqyi87_profile.py

RUN sed -i 's/VERSION = "1.6.5"/VERSION = "1.6.6"/' /app/server.py \
    && python3 -m py_compile /app/server.py /app/cqyi87_profile.py

CMD ["python3", "/app/server.py"]
