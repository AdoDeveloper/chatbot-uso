import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";
import { AuthProvider } from "@/contexts/auth-context";
import { ProgressBarProvider } from "@/components/composed/progress-bar-provider";

// Inter con weights explícitos. El variable font (sin array de weight) no
// estaba sirviendo correctamente vía next/font en este setup, causando
// fallback a serif (Times New Roman). Volvemos a la config estática que
// funcionaba antes con los pesos que realmente usa el design system.
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  display: "swap",
  fallback: ["system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
});

// JetBrains Mono se mantiene solo para snippets de codigo (panel admin tiene
// previews de embed snippets, regex de guardrails, etc). El sitio publico no
// la necesita.
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  display: "swap",
  fallback: ["ui-monospace", "Menlo", "Monaco", "monospace"],
});

export const metadata: Metadata = {
  title: "Chatbot Admin",
  description: "Panel de administración del chatbot",
  icons: [{ rel: "icon", url: "/favicon.ico" }],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className={`${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="antialiased">
        {/* Skip-to-content for keyboard/screen-reader users. Visually hidden
            until focused, then reveals as a pill at the top-left. */}
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-200 focus:rounded-md focus:bg-primary focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium focus:text-primary-foreground focus:shadow-md focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        >
          Ir al contenido
        </a>
        <ProgressBarProvider>
          <AuthProvider>
            {children}
            <Toaster position="bottom-right" richColors closeButton />
          </AuthProvider>
        </ProgressBarProvider>
      </body>
    </html>
  );
}
