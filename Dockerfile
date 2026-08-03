# --- desenvolvimento: sem código embutido, chega por bind mount ---
FROM python:3.12-slim AS dev

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# O Pyright baixa o próprio Node, que precisa de libatomic - ausente na
# imagem slim. Sem isso ele falha com "libatomic.so.1: cannot open shared
# object file", mensagem que não sugere a solução.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*

# O ambiente virtual fica fora de /app: com bind mount, um .venv em /app
# seria escrito na pasta do host, misturando binários do container com o WSL.
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Usuário com o mesmo UID do host. Sem isso, todo arquivo gerado dentro do
# container - migration do autogenerate, cache do pytest - nasce como root
# na pasta do host, e o editor não consegue mais alterá-lo.
ARG UID=1000
ARG GID=1000
RUN groupadd -g "$GID" app 2>/dev/null || true \
    && useradd -u "$UID" -g "$GID" -m -s /bin/bash app 2>/dev/null || true \
    && mkdir -p /opt/venv /app \
    && chown -R "$UID:$GID" /opt/venv /app

USER app
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
