FROM python:3.13-slim AS builder

ARG UV_VERSION=0.11.15
RUN python -m pip install --no-cache-dir "uv==${UV_VERSION}"

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --no-editable


FROM python:3.13-slim AS runtime

LABEL org.opencontainers.image.title="iCloudHarbor" \
    org.opencontainers.image.description="Reliable iCloud Photos backup for Linux and NAS" \
    org.opencontainers.image.source="https://github.com/lwx-cloud/icloudHarbor" \
    org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates gosu tini tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 icloudharbor \
    && useradd --uid 1000 --gid 1000 --home-dir /nonexistent --no-create-home \
        --shell /usr/sbin/nologin icloudharbor

ENV PATH="/app/.venv/bin:${PATH}" \
    HOME=/config \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IH_CONFIG_FILE=/config/config.yaml

COPY --from=builder /app/.venv /app/.venv
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 0755 /usr/local/bin/entrypoint.sh \
    && mkdir -p \
        /config/credentials /config/database /config/sessions /config/locks /config/tmp /photos \
    && chown -R icloudharbor:icloudharbor /config

VOLUME ["/config", "/photos"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["icloudharbor", "daemon"]

HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD ["icloudharbor", "healthcheck", "--liveness"]
