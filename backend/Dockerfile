# ── Stage 1: Builder — compila las dependencias (gcc) en una imagen aparte ────
FROM python:3.12-slim AS builder

WORKDIR /app

# Forzar HTTPS para apt (el puerto 80 HTTP puede estar bloqueado por el firewall)
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list 2>/dev/null || true

# Build deps — solo en el builder, NO en la imagen final.
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

# Instala las dependencias en un prefijo aislado para copiarlo al runtime.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime — sin compiladores, superficie mínima ────────────────────
FROM python:3.12-slim

WORKDIR /app

# Forzar HTTPS para apt
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list 2>/dev/null || true

# Solo runtime deps (curl para healthchecks/diagnóstico). Sin gcc.
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copia las librerías Python ya compiladas desde el builder.
COPY --from=builder /install /usr/local

# ── Non-root user ────────────────────────────────────────────────────────────
RUN groupadd -r appuser && useradd -r -g appuser -m appuser

# ── Source code (includes static/widget/widget.js pre-built) ─────────────────
COPY --chown=appuser:appuser . .

RUN chmod +x entrypoint.sh

# Ensure upload dir and cache dirs are accessible by appuser.
# Se pre-crean fastembed/ y flashrank/ explícitamente para que Docker inicialice
# los volúmenes nombrados con ownership de appuser (no de root).
# Si solo se crea el directorio padre (.cache) Docker crea el subdirectorio
# del volumen como root en el primer arranque → Permission denied al escribir.
RUN mkdir -p \
        /app/uploads \
        /home/appuser/.cache/fastembed \
        /home/appuser/.cache/flashrank \
    && chown -R appuser:appuser /app/uploads /home/appuser/.cache

EXPOSE 8000

USER appuser

ENTRYPOINT ["./entrypoint.sh"]
