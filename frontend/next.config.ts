import path from "node:path";
import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// CSP propia del panel: 'unsafe-inline' en script-src es por la hidratación de Next.js sin nonce, pero bloquea <script src> de terceros (el vector XSS más común); el markdown del chatbot igual se sanitiza con DOMPurify.
const apiOrigin = (() => {
  try {
    return process.env.NEXT_PUBLIC_API_URL
      ? new URL(process.env.NEXT_PUBLIC_API_URL).origin
      : "";
  } catch {
    return "";
  }
})();

function buildCsp(isDevelopment: boolean): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${isDevelopment ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: http: https:",
    "font-src 'self' data:",
    `connect-src 'self' ${apiOrigin}`.trim(),
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
}

const BACKEND_INTERNAL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const APP_ORIGIN = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000");
  } catch {
    return new URL("http://localhost:3000");
  }
})();

export default (phase: string): NextConfig => {
  const isDevelopment = phase === PHASE_DEVELOPMENT_SERVER;
  const csp = buildCsp(isDevelopment);

  return {
    output: "standalone",
    outputFileTracingRoot: path.join(__dirname),
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
