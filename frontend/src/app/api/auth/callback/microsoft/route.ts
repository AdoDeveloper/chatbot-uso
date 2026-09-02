import { NextRequest, NextResponse } from "next/server";
import { APP_URL, BASE_URL } from "@/lib/config";

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const error = searchParams.get("error");
  const errorDescription = searchParams.get("error_description");

  const appOrigin = APP_URL;
  const redirectUri = `${appOrigin}/api/auth/callback/microsoft`;

  const loginUrl = (msg: string) =>
    new URL(`/login?error=${encodeURIComponent(msg)}`, appOrigin);

  if (error || !code) {
    const msg = errorDescription ?? error ?? "Inicio de sesión cancelado";
    return NextResponse.redirect(loginUrl(msg));
  }

  // Validar state CSRF (RFC 6749 §10.12): comparar con la cookie que se guardó al iniciar el flujo
  const savedState = request.cookies.get("oauth_state")?.value;

  if (!state || !savedState || state !== savedState) {
    console.error("[microsoft/callback] state mismatch", { hasState: !!state, hasSavedState: !!savedState });
    return NextResponse.redirect(loginUrl("Credenciales incorrectas"));
  }

  try {
    const resp = await fetch(`${BASE_URL}/api/v1/auth/microsoft/callback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, redirect_uri: redirectUri }),
    });

    if (!resp.ok) {
      console.error("[microsoft/callback] backend rejected", resp.status, await resp.text());
      return NextResponse.redirect(loginUrl("Credenciales incorrectas"));
    }

    const { access_token, refresh_token } = await resp.json() as {
      access_token: string;
      refresh_token: string;
    };

    const response = NextResponse.redirect(new URL("/dashboard", appOrigin));

    // Limpiar la cookie de state una vez usado
    response.cookies.delete("oauth_state");

    // Modo Bearer: las cookies son legibles por JS para que lib/api.ts (js-cookie)
    // pueda adjuntar el header Authorization. httpOnly siempre es false.
    const isHttps = appOrigin.startsWith("https://");
    response.cookies.set("chatbot_access", access_token, {
      maxAge: 60 * 60 * 24,
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      secure: isHttps,
    });
    response.cookies.set("chatbot_refresh", refresh_token, {
      maxAge: 60 * 60 * 24 * 7,
      httpOnly: false,
      sameSite: "lax",
      path: "/",
      secure: isHttps,
    });

    return response;
  } catch (err) {
    console.error("[microsoft/callback] fetch to backend failed", err instanceof Error ? err.message : err, "BACKEND=", BASE_URL);
    return NextResponse.redirect(loginUrl("Credenciales incorrectas"));
  }
}
