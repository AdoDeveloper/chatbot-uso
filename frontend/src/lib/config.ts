/**
 * Configuración central de URLs — única fuente de verdad.
 *
 * Antes BASE_URL estaba duplicada en lib/api.ts, login/page.tsx y el callback
 * OAuth, cada una con su propio fallback. Cualquier cambio de URL ahora se
 * hace solo aquí (o vía variables de entorno, que es lo correcto en deploy).
 */

/** URL pública del backend, visible desde el navegador. */
export const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** URL pública de esta app Next.js (se usa para construir redirect_uri de OAuth). */
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

/**
 * URL del backend para llamadas server-side (route handlers / middleware).
 * En Docker apunta a la red interna (http://backend:8000); en el navegador
 * BACKEND_URL no existe y cae a BASE_URL.
 */
export const BACKEND_INTERNAL_URL = process.env.BACKEND_URL ?? BASE_URL;
