FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
ARG RELEASE_VERSION="main"

WORKDIR /app
COPY . .
# No uv.lock is committed for the prior-authorization example; resolve at build time.
RUN uv sync --no-cache --link-mode copy

ENV PRODUCTION_MODE=True \
    RELEASE_VERSION=${RELEASE_VERSION}

RUN chown -R 1001:1001 /app
USER 1001

CMD ["uv", "run", "--no-sync", "priorauth_coding_tool.py"]
