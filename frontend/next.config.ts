import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// CSP: el panel solo carga recursos propios. `connect-src` incluye el backend
// (NEXT_PUBLIC_API_URL) para las llamadas XHR/fetch y SSE del playground.
// 'unsafe-inline' en script-src es necesario por la hidratación de Next.js sin
// nonce; aun así se bloquea la carga de <script src> de terceros — el vector
// XSS más común. El markdown del chatbot se sanitiza con DOMPurify antes de
// renderizar, por lo que no se requiere relajar la política para ello.
const apiOrigin = (() => {
  try {
    return process.env.NEXT_PUBLIC_API_URL
      ? new URL(process.env.NEXT_PUBLIC_API_URL).origin
      : "";
  } catch {
    return "";
  }
})();

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}`.trim(),
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const BACKEND_INTERNAL = process.env.BACKEND_INTERNAL_URL ?? "http://127.0.0.1:8000";
const APP_ORIGIN = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000");
  } catch {
    return new URL("http://localhost:3000");
  }
})();

export default (phase: string): NextConfig => {
  const isDevelopment = phase === PHASE_DEVELOPMENT_SERVER;

  return {
    output: "standalone",
    allowedDevOrigins: isDevelopment ? [APP_ORIGIN.hostname] : undefined,
    async rewrites() {
      return [
        {
          source: "/api/:path*",
          destination: `${BACKEND_INTERNAL}/api/:path*`,
        },
      ];
    },
    async headers() {
      return [
        {
          source: "/(.*)",
          headers: [
            { key: "X-Content-Type-Options", value: "nosniff" },
            { key: "X-Frame-Options", value: "DENY" },
            { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
            {
              key: "Permissions-Policy",
              value: "geolocation=(), microphone=(), camera=()",
            },
            {
              key: "X-DNS-Prefetch-Control",
              value: "on",
            },
            {
              key: "Strict-Transport-Security",
              value: "max-age=63072000; includeSubDomains; preload",
            },
            { key: "Content-Security-Policy", value: csp },
          ],
        },
      ];
    },
  };
};
