
/** URL pública del backend, visible desde el navegador. */
export const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** URL pública de esta app Next.js (se usa para construir redirect_uri de OAuth). */
export const APP_URL = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";
