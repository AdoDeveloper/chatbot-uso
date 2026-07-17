"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import api from "@/lib/api";

/** Extrae el `detail` que envía el backend en errores HTTP, con fallback genérico. */
export function getErrorMessage(err: unknown, fallback = "No se pudo cargar la información. Inténtelo de nuevo más tarde."): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((e: { msg?: string }) => e.msg ?? "Error de validación").join(". ");
  }
  if (detail && typeof detail === "object" && typeof (detail as { message?: string }).message === "string") {
    return (detail as { message: string }).message;
  }
  return fallback;
}

export interface UseApiResult<T> {
  data: T | null;
  loading: boolean;
  refetching: boolean;
  error: string | null;
  refetch: () => Promise<void>;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
}

/**
 * Caché en memoria por path para no re-fetchear en cada montaje de vista.
 * Al volver a una vista, los datos aparecen al instante (desde caché) y se
 * revalidan en background. TTL corto: los datos siguen siendo frescos.
 */
const CACHE_TTL_MS = 30_000;
const _cache = new Map<string, { data: unknown; ts: number }>();

function _cacheGet(path: string): unknown | null {
  const hit = _cache.get(path);
  if (!hit) return null;
  if (Date.now() - hit.ts > CACHE_TTL_MS) {
    _cache.delete(path);
    return null;
  }
  return hit.data;
}

function _cacheSet(path: string, data: unknown): void {
  _cache.set(path, { data, ts: Date.now() });
}

/**
 * Ciclo completo de GET a la API: loading/refetching, error con `detail` del
 * backend, cancelación con AbortController al desmontar o cambiar deps, y
 * nunca setState tras unmount.
 *
 *   const { data, loading, error, refetch } = useApi<Source[]>("/sources");
 *
 *   // Recarga sola cuando cambia el filtro:
 *   const { data } = useApi<TopicsResponse>(`/analytics/topics?days=${days}`, [days]);
 *
 *   // Carga condicional — `null` pospone el fetch (p. ej. faltan fechas):
 *   const { data } = useApi<Metrics>(ready ? `/analytics?${qs}` : null, [ready, qs]);
 */
export function useApi<T>(path: string | null, deps: unknown[] = []): UseApiResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(path !== null);
  const [refetching, setRefetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Para que `refetch` sea estable sin re-suscribir el efecto.
  const hasData = useRef(false);
  const pathRef = useRef(path);
  pathRef.current = path;

  const load = useCallback(async (signal?: AbortSignal, force = false) => {
    const current = pathRef.current;
    if (current === null) return;

    // Caché: si hay datos frescos y no forzamos, mostramos al instante y
    // revalidamos en background (sin loading). Mejora la percepción de velocidad
    // al navegar entre vistas.
    const cached = force ? null : _cacheGet(current);
    if (cached !== null) {
      setData(cached as T);
      hasData.current = true;
      if (signal?.aborted) return;
    }

    const isBackground = cached !== null;
    if (isBackground) setRefetching(true);
    else if (hasData.current) setRefetching(true);
    else setLoading(true);
    setError(null);

    try {
      const { data } = await api.get<T>(current, { signal });
      if (signal?.aborted) return;
      _cacheSet(current, data);
      setData(data);
      hasData.current = true;
    } catch (err) {
      if (signal?.aborted) return;
      // En revalidación de fondo, no pisamos los datos en caché con un error.
      if (!isBackground) setError(getErrorMessage(err));
    } finally {
      if (!signal?.aborted) {
        setLoading(false);
        setRefetching(false);
      }
    }
  }, []);

  useEffect(() => {
    if (path === null) return;
    const ctrl = new AbortController();
    void load(ctrl.signal);
    return () => ctrl.abort();
    // `path` ya cambia cuando cambian sus insumos; deps cubre casos indirectos.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);

  const refetch = useCallback(() => load(undefined, true), [load]);

  return { data, loading, refetching, error, refetch, setData };
}
