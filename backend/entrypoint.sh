#!/bin/sh
set -e

# Esperar a Qdrant (su imagen no tiene curl/wget — usamos Python que sí está disponible)
# Límite de intentos para no colgar el arranque si Qdrant no levanta nunca.
echo "Waiting for Qdrant at qdrant:6333..."
QDRANT_ATTEMPTS=60
for _ in $(seq 1 $QDRANT_ATTEMPTS); do
    if python3 -c "
import urllib.request, sys
try:
    urllib.request.urlopen('http://qdrant:6333/', timeout=3)
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
        echo " Qdrant ready."
        break
    fi
    printf '.'
    sleep 2
    if [ "$_" -eq "$QDRANT_ATTEMPTS" ]; then
        echo ""
        echo "WARNING: Qdrant no respondió tras $QDRANT_ATTEMPTS intentos — continuando de todas formas."
    fi
done

# Esperar a que MySQL esté realmente listo para aceptar conexiones.
# El healthcheck de Docker pasa durante el servidor temporal de init, pero
# MySQL lo apaga y arranca el real poco después — hay una ventana de ~2 s sin
# conexión que coincide con el primer intento de Alembic. Este bucle espera
# hasta que aiomysql logra abrir una conexión real antes de continuar.
echo "Waiting for MySQL at mysql:3306..."
python3 - <<'PYEOF'
import asyncio, os, re, sys

async def wait_mysql(max_attempts: int = 30, delay: float = 2.0) -> None:
    url = os.environ.get("DATABASE_URL", "")
    m = re.match(r"mysql\+aiomysql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", url)
    if not m:
        print("No se pudo parsear DATABASE_URL — continuando sin esperar.")
        return
    user, password, host, port, db = m.groups()
    import aiomysql
    for attempt in range(1, max_attempts + 1):
        try:
            conn = await aiomysql.connect(
                host=host, port=int(port),
                user=user, password=password, db=db,
                connect_timeout=3,
            )
            await conn.ensure_closed()
            print(f" MySQL listo (intento {attempt}).")
            return
        except Exception:
            if attempt < max_attempts:
                sys.stdout.write(".")
                sys.stdout.flush()
                await asyncio.sleep(delay)
    print("\nWARNING: MySQL no respondió tras 30 intentos — se intenta Alembic de todas formas.")

asyncio.run(wait_mysql())
PYEOF

# alembic upgrade head es idempotente gracias a los helpers _ct/_ci de la
# migración 0001: si una tabla ya existe (DDL no-transaccional de MySQL) la
# salta en lugar de fallar. En caso de error inesperado se aborta el arranque.
echo "Running database migrations..."
if ! alembic upgrade head; then
    echo "ERROR: alembic upgrade head falló — abortando."
    exit 1
fi
echo "Migrations complete."

# ── Pre-download de modelos (solo si el cache está vacío) ─────────────────────
# Los archivos de modelo están pinados al contenido exacto definido en el
# registry de fastembed==0.4.2 (requirements.txt). Cada versión del paquete
# hardcodea las URLs + checksums SHA256 de los modelos, por lo que actualizar
# fastembed puede cambiar los binarios descargados — actualizar con cuidado.
# HF_HUB_OFFLINE=1 (del docker-compose) evita las ~120 requests de validación
# a HuggingFace por worker en arranques posteriores.

# Verificar que la versión instalada coincide con la esperada.
EXPECTED_FASTEMBED="0.4.2"
INSTALLED_FASTEMBED=$(python3 -c "import fastembed; print(fastembed.__version__)" 2>/dev/null || echo "unknown")
if [ "$INSTALLED_FASTEMBED" != "$EXPECTED_FASTEMBED" ]; then
    echo "WARNING: fastembed version mismatch — expected $EXPECTED_FASTEMBED, got $INSTALLED_FASTEMBED"
    echo "         Los modelos descargados pueden no coincidir con los esperados."
fi

CACHE_DIR="${HOME}/.cache/fastembed"
if [ ! -d "$CACHE_DIR/models--Qdrant--multilingual-e5-large-onnx" ]; then
    echo "First run: downloading embedding models (this only happens once)..."
    HF_HUB_OFFLINE=0 python3 -c "
import os
cache = os.environ.get('HOME', '/home/appuser') + '/.cache/fastembed'
from fastembed import TextEmbedding, SparseTextEmbedding
TextEmbedding('intfloat/multilingual-e5-large', cache_dir=cache)
SparseTextEmbedding('Qdrant/bm25', cache_dir=cache)
print('Models downloaded successfully.')
"
fi

# Producción: gunicorn + uvicorn workers.
# Cada worker carga su propia copia de los modelos (~1.7 GB cada uno).
# Default = 1 worker (seguro para servidores de 4 GB de RAM). Subir SOLO si hay
# RAM de sobra: 8 GB → WORKERS=2, 16 GB → WORKERS=4+. Con 4 GB, 2 workers (~3.4 GB
# en modelos) provoca OOM al arrancar.
# Sobreescribe con: WORKERS=2 docker compose up
WORKERS=${WORKERS:-1}
exec gunicorn app.main:app \
    --bind 0.0.0.0:8000 \
    --worker-class uvicorn.workers.UvicornWorker \
    --workers "$WORKERS" \
    --timeout 300 \
    --graceful-timeout 30
