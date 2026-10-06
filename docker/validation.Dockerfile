# Trusted validation image: build separately; never build an uploaded Dockerfile.
FROM python:3.13-slim
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then cp /run/secrets/build_ca /usr/local/share/ca-certificates/session-build.crt; update-ca-certificates; fi; \
    python -m pip install --no-cache-dir pytest==9.0.2 ruff==0.15.7 mypy==1.19.1
WORKDIR /workspace
USER 65534:65534
