export interface JwtPayload {
  sub?: string;
  exp?: number;
  iat?: number;
  jti?: string;
  type?: string;
  permissions?: string[];
}

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
