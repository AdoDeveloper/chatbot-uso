"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { isAxiosError } from "axios";
import api, { tokenStore } from "@/lib/api";
import { decodeJwt } from "@/lib/jwt";
import { logger } from "@/lib/logger";
import type { TokenResponse, User } from "@/types";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  permissions: Set<string>;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  refreshPermissions: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// Evento que el interceptor de axios despacha tras una rotación silenciosa de
// tokens: el access token nuevo trae permisos frescos, así que re-decodificamos.
export const TOKENS_REFRESHED_EVENT = "auth:tokens-refreshed";

// Permisos desde el JWT (claim `permissions`). Es la fuente preferida: se
// incrustan al emitir el token, por lo que están disponibles de inmediato sin
// una llamada extra y no dependen de la disponibilidad de /rbac/my-permissions.
// La firma del token la valida el backend; aquí solo leemos para la UI.
function permsFromToken(): Set<string> | null {
  const payload = decodeJwt(tokenStore.getAccess());
  const p = payload?.permissions;
  return Array.isArray(p) ? new Set(p) : null;
}

// Fallback para tokens emitidos antes de incrustar permisos en el JWT.
async function fetchPermissionsFromApi(): Promise<Set<string> | null> {
  try {
    const { data } = await api.get<{ permissions: string[] }>("/rbac/my-permissions");
    return new Set(data.permissions);
  } catch (err) {
    logger.error("[auth] fetchPermissions failed:", err);
    return null;
  }
}

// Resuelve permisos: JWT primero; si el token no trae el claim (token antiguo)
// o falla, cae a la API. Devuelve null si ambas fallan, para que el llamador
// conserve el valor previo (fail-closed solo en error real, nunca por rol).
async function resolvePermissions(): Promise<Set<string> | null> {
  const fromToken = permsFromToken();
  if (fromToken) return fromToken;
  return fetchPermissionsFromApi();
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [permissions, setPermissions] = useState<Set<string>>(new Set());

  const refreshUser = useCallback(async () => {
    try {
      const { data } = await api.get<User>("/auth/me");
      setUser(data);
      const next = await resolvePermissions();
      setPermissions((prev) => next ?? prev);
      const currentPath = pathnameRef.current;
      if (data.must_change_password && !currentPath.startsWith("/cambiar-contrasena")) {
        router.push("/cambiar-contrasena");
      } else if (!data.must_change_password && currentPath.startsWith("/cambiar-contrasena")) {
        router.push("/dashboard");
      }
    } catch (err: unknown) {
      // Solo una sesión realmente inválida (401) debe cerrar sesión. Un error
      // de red, CORS o 5xx transitorio no implica que el token sea inválido —
      // limpiarlo en ese caso desloguea al usuario innecesariamente ante un
      // problema de conectividad temporal.
      if (isAxiosError(err) && err.response?.status === 401) {
        tokenStore.clear();
        setUser(null);
        setPermissions(new Set());
      }
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const refreshPermissions = useCallback(async () => {
    if (!user) return;
    const next = await resolvePermissions();
    setPermissions((prev) => next ?? prev);
  }, [user]);

  useEffect(() => {
    const token = tokenStore.getAccess();
    if (!token) {
      setLoading(false);
      return;
    }
    refreshUser().finally(() => setLoading(false));
  }, [refreshUser]);

  // Tras una rotación silenciosa de tokens (interceptor 401→/auth/refresh), el
  // nuevo access token puede traer permisos actualizados: re-decodificamos.
  useEffect(() => {
    function onRefreshed() {
      const p = permsFromToken();
      if (p) setPermissions(p);
    }
    window.addEventListener(TOKENS_REFRESHED_EVENT, onRefreshed);
    return () => window.removeEventListener(TOKENS_REFRESHED_EVENT, onRefreshed);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const { data } = await api.post<TokenResponse>("/auth/login", { email, password });
    tokenStore.set(data.access_token, data.refresh_token);
    setUser(data.user);
    const next = permsFromToken() ?? (await fetchPermissionsFromApi());
    setPermissions((prev) => next ?? prev);
    if (data.user.must_change_password) {
      router.push("/cambiar-contrasena");
    } else {
      router.push("/dashboard");
    }
  }, [router]);

  const logout = useCallback(async () => {
    // Revoca los tokens en el backend (denylist) y limpia las cookies httpOnly.
    // Best-effort: si la red falla igualmente limpiamos el estado local.
    try {
      await api.post("/auth/logout", { refresh_token: tokenStore.getRefresh() });
    } catch {
      /* ignore — el cierre de sesión local procede de todos modos */
    }
    tokenStore.clear();
    setUser(null);
    setPermissions(new Set());
    router.push("/login");
  }, [router]);

  const ctxValue = useMemo(() => ({
    user, loading, permissions, login, logout, refreshUser, refreshPermissions,
  }), [user, loading, permissions, login, logout, refreshUser, refreshPermissions]);

  return (
    <AuthContext.Provider value={ctxValue}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
