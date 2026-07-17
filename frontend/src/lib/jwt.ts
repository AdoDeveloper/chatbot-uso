export interface JwtPayload {
  sub?: string;
  exp?: number;
  iat?: number;
  jti?: string;
  type?: string;
  permissions?: string[];
}

/**
 * Decodifica la parte payload de un JWT (base64url) SIN verificar la firma.
 * La firma la valida el backend; aquí solo leemos el claim `permissions` para
 * resolver la visibilidad de la navegación en el cliente. Si el token es
 * inválido o no tiene payload, devolvemos null.
 */
export function decodeJwt(token: string | null | undefined): JwtPayload | null {
  if (!token) return null;
  const part = token.split(".")[1];
  if (!part) return null;
  try {
    const b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    const json =
      typeof atob !== "undefined"
        ? atob(b64)
        : Buffer.from(b64, "base64").toString("utf-8");
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
}
