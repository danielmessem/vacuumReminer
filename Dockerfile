ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 docker-cli

WORKDIR /app
COPY server_y1_v160.py /app/server_y1_v160.py
COPY server_wrapper_v181.py /app/server.py
COPY cqyi87_profile.py /app/cqyi87_profile.py

RUN python3 -m py_compile /app/server_y1_v160.py /app/server.py /app/cqyi87_profile.py

CMD ["python3", "/app/server.py"]
