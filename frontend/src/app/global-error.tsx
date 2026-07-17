"use client";

// Fallback de último recurso: solo se activa si el propio layout raíz falla.
// Reemplaza todo el documento, por eso incluye <html> y <body> propios y no
// puede depender de los providers ni de los estilos del layout.

export default function GlobalError({
  error: _error,
  reset: _reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="es">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f8fafc",
          fontFamily:
            "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
          color: "#1f2937",
          padding: "16px",
        }}
      >
        <div style={{ maxWidth: "360px", textAlign: "center" }}>
          <div
            style={{
              margin: "0 auto 16px",
              width: "48px",
              height: "48px",
              borderRadius: "9999px",
              background: "rgba(185,28,28,0.1)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#b91c1c"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
          </div>
          <h1 style={{ fontSize: "20px", fontWeight: 600, margin: "0 0 8px" }}>
            Algo salió mal
          </h1>
          <p style={{ fontSize: "14px", color: "#6b7280", margin: "0 0 20px", lineHeight: 1.6 }}>
            Ocurrió un error inesperado. Intente de nuevo o recargue la página.
          </p>
          <button
            onClick={() => _reset()}
            style={{
              height: "36px",
              padding: "0 18px",
              borderRadius: "8px",
              border: "none",
              background: "#1e40af",
              color: "#ffffff",
              fontSize: "14px",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Intentar de nuevo
          </button>
        </div>
      </body>
    </html>
  );
}
