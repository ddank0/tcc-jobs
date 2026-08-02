# --- desenvolvimento: sem código embutido, chega por bind mount ---
FROM python:3.12-slim AS dev

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# O ambiente virtual fica fora de /app: com bind mount, um .venv em /app
# seria escrito na pasta do host, misturando binários do container com o WSL.
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
CMD ["sleep", "infinity"]

# --- produção: código embutido, sem dependências de desenvolvimento ---
FROM python:3.12-slim AS prod

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .

ENTRYPOINT ["uv", "run", "tcc"]
CMD ["--help"]
