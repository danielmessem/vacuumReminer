ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 docker-cli

WORKDIR /app
COPY server_y1_v160.py /app/server_y1_v160.py
COPY server_wrapper_v181.py /app/server_wrapper_v181.py
COPY server_hotfix_v203.py /app/server_hotfix_v203.py
COPY server_hotfix_v210.py /app/server_hotfix_v210.py
COPY server_hotfix_v211.py /app/server_hotfix_v211.py
COPY server_hotfix_v212.py /app/server_hotfix_v212.py
COPY server_hotfix_v213.py /app/server_hotfix_v213.py
COPY server_hotfix_v214.py /app/server_hotfix_v214.py
COPY server_hotfix_v215.py /app/server_hotfix_v215.py
COPY server_hotfix_v216.py /app/server_hotfix_v216.py
COPY server_hotfix_v217.py /app/server_hotfix_v217.py
COPY server_hotfix_v218.py /app/server_hotfix_v218.py
COPY server_hotfix_v219.py /app/server_hotfix_v219.py
COPY server_hotfix_v220.py /app/server_hotfix_v220.py
COPY server_hotfix_v221.py /app/server_hotfix_v221.py
COPY server_hotfix_v222.py /app/server_hotfix_v222.py
COPY server_hotfix_v223.py /app/server_hotfix_v223.py
COPY server_hotfix_v224.py /app/server.py
COPY cqyi87_profile.py /app/cqyi87_profile.py

RUN python3 -m py_compile /app/server_y1_v160.py /app/server_wrapper_v181.py /app/server_hotfix_v203.py /app/server_hotfix_v210.py /app/server_hotfix_v211.py /app/server_hotfix_v212.py /app/server_hotfix_v213.py /app/server_hotfix_v214.py /app/server_hotfix_v215.py /app/server_hotfix_v216.py /app/server_hotfix_v217.py /app/server_hotfix_v218.py /app/server_hotfix_v219.py /app/server_hotfix_v220.py /app/server_hotfix_v221.py /app/server_hotfix_v222.py /app/server_hotfix_v223.py /app/server.py /app/cqyi87_profile.py

CMD ["python3", "/app/server.py"]
