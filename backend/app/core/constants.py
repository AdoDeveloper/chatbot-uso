from __future__ import annotations

PLAYGROUND_BROWSERS: frozenset[str] = frozenset({"playground", "panel", "admin"})

# Valor de `browser` que envía el previsualizador del panel cuando el modo es
# "Producción" (config y fuentes desplegadas, no el borrador). No pertenece a
# PLAYGROUND_BROWSERS a propósito: ese turno debe contar en las estadísticas
# igual que el tráfico del widget, porque ejercita exactamente lo que ve un
# usuario final - a diferencia del modo borrador, que sí queda excluido.
PREVIEW_PRODUCTION_BROWSER = "preview-production"

# Todo lo que llega desde el panel autenticado (JWT) en vez del widget público
# (API key): el modo borrador y el modo "Producción" del previsualizador.
# Distinta de PLAYGROUND_BROWSERS porque ambos conjuntos responden preguntas
# diferentes - "¿requiere JWT en vez de widget key?" vs. "¿se excluye de las
# estadísticas?" - y preview-production es sí a la primera, no a la segunda.
PANEL_AUTHENTICATED_BROWSERS: frozenset[str] = PLAYGROUND_BROWSERS | {PREVIEW_PRODUCTION_BROWSER}
