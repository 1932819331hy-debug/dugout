FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version README.md ./
COPY packages ./packages
COPY config ./config
RUN uv sync --frozen --no-dev
COPY . .
ENTRYPOINT ["uv", "run", "--no-dev", "dugout"]
CMD ["ingest", "--job", "nightly"]
