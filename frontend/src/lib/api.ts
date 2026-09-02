import axios, { AxiosInstance, InternalAxiosRequestConfig } from "axios";
import Cookies from "js-cookie";
import { BASE_URL } from "@/lib/config";
import type { TokenResponse } from "@/types";

const API_PREFIX = "/api/v1";

/** Construye una URL absoluta a un endpoint de la API. Útil para descargas
 * directas (exports CSV/JSON, streams de archivos) donde no se puede usar
 * la instancia de axios porque el navegador maneja la respuesta directamente vía window.open o <a>.
 *
 * Pasar el path SIN el prefijo /api/v1, ej. apiUrl("/audit/logs/export").
 */
export function apiUrl(path: string): string {
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${BASE_URL}${API_PREFIX}${clean}`;
}

const ACCESS_TOKEN_KEY = "chatbot_access";
const REFRESH_TOKEN_KEY = "chatbot_refresh";

// Tokens guardados en cookies legibles por JS (modo Bearer).
// El flag secure se activa automáticamente cuando se sirve por HTTPS.
export const tokenStore = {
  getAccess: () => Cookies.get(ACCESS_TOKEN_KEY) ?? null,
  getRefresh: () => Cookies.get(REFRESH_TOKEN_KEY) ?? null,
  set: (access: string, refresh: string) => {
    const secure = typeof location !== "undefined" && location.protocol === "https:";
    Cookies.set(ACCESS_TOKEN_KEY, access, { expires: 1, sameSite: "strict", secure });
    Cookies.set(REFRESH_TOKEN_KEY, refresh, { expires: 7, sameSite: "strict", secure });
  },
  clear: () => {
    Cookies.remove(ACCESS_TOKEN_KEY);
    Cookies.remove(REFRESH_TOKEN_KEY);
  },
};

const api: AxiosInstance = axios.create({
  baseURL: `${BASE_URL}${API_PREFIX}`,
  headers: { "Content-Type": "application/json" },
});

// Adjunta el token Bearer a cada petición (solo en modo header).
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  config.headers = config.headers ?? {};
  const token = tokenStore.getAccess();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // Para FormData, quita el Content-Type JSON por defecto para que el navegador
  // configure multipart/form-data con el boundary correcto automáticamente.
  if (config.data instanceof FormData) {
    delete config.headers["Content-Type"];
  }
  return config;
});

let isRefreshing = false;
type QueueItem = { resolve: (v: string) => void; reject: (e: unknown) => void };
let failedQueue: QueueItem[] = [];

function processQueue(error: unknown, token: string | null) {
  failedQueue.forEach(({ resolve, reject }) => (token ? resolve(token) : reject(error)));
  failedQueue = [];
}

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config;

    // No intentar refresh en endpoints de auth (un 401 ahí significa credenciales
    // incorrectas, no token expirado - sin este check entra en bucle de reload)
    const isAuthEndpoint = original.url?.includes("/auth/login") ||
                           original.url?.includes("/auth/refresh") ||
                           original.url?.includes("/auth/invite");

    if (error.response?.status !== 401 || original._retry || isAuthEndpoint) {
      return Promise.reject(error);
    }

    if (isRefreshing) {
      return new Promise<string>((resolve, reject) => {
        failedQueue.push({ resolve, reject });
      }).then((token) => {
        original.headers.Authorization = `Bearer ${token}`;
        return api(original);
      });
    }

    original._retry = true;
    isRefreshing = true;

    const refreshToken = tokenStore.getRefresh();
    if (!refreshToken) {
      isRefreshing = false;
      processQueue(error, null);
      tokenStore.clear();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(error);
    }

     try {
       const { data } = await axios.post<TokenResponse>(
         `${BASE_URL}${API_PREFIX}/auth/refresh`,
         { refresh_token: refreshToken },
       );
       tokenStore.set(data.access_token, data.refresh_token);
       // El nuevo access token puede traer permisos actualizados: avisamos al
       // AuthProvider para que re-decodifique y refresque la UI.
       if (typeof window !== "undefined") {
         window.dispatchEvent(new Event("auth:tokens-refreshed"));
       }
       processQueue(null, data.access_token);
      original.headers.Authorization = `Bearer ${data.access_token}`;
      return api(original);
    } catch (err) {
      processQueue(err, null);
      tokenStore.clear();
      if (typeof window !== "undefined") window.location.href = "/login";
      return Promise.reject(err);
    } finally {
      isRefreshing = false;
    }
  }
);

export default api;
