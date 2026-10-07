FROM node:24-bookworm-slim AS admin-build
WORKDIR /build/admin-web
COPY admin-web/package*.json ./
RUN --mount=type=secret,id=session_ca if [ -f /run/secrets/session_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/session_ca; fi; npm ci --ignore-scripts
COPY admin-web/ ./
RUN npm run build

FROM python:3.13-slim-trixie
ARG BUILD_GIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BUILD_GIT_SHA=$BUILD_GIT_SHA BUILD_TIMESTAMP=$BUILD_TIMESTAMP
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates postgresql-client && rm -rf /var/lib/apt/lists/* && useradd --uid 10001 --create-home agent
COPY requirements.txt ./
RUN --mount=type=secret,id=session_ca if [ -f /run/secrets/session_ca ]; then export PIP_CERT=/run/secrets/session_ca; fi; pip install --no-cache-dir -r requirements.txt && python -m pip uninstall -y pip setuptools wheel
COPY app/ app/
COPY alembic/ alembic/
COPY scripts/ scripts/
COPY alembic.ini pyproject.toml ./
COPY --from=admin-build /build/admin-web/dist admin-web/dist
RUN mkdir -p storage/workspaces && chown -R agent:agent /app
USER agent
EXPOSE 8000
CMD ["sh", "scripts/start.sh"]
