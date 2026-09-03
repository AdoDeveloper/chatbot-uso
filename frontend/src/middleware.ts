import { NextRequest, NextResponse } from "next/server";
import { APP_URL } from "@/lib/config";

export function middleware(request: NextRequest) {
  const token = request.cookies.get("chatbot_access")?.value;
  const { pathname } = request.nextUrl;

  const isAuth = pathname.startsWith("/login") || pathname.startsWith("/invite");
  const isDashboard = pathname.startsWith("/dashboard");
  const isChangePassword = pathname.startsWith("/cambiar-contrasena");

  // request.url resuelve al host interno del proceso Node (localhost:3000)
  // detrás de un reverse proxy en modo standalone, no al dominio público -
  // ver https://github.com/vercel/next.js/issues/37662. Se construye la URL
  // de redirect a partir de APP_URL (NEXT_PUBLIC_APP_URL) en su lugar.
  if ((isDashboard || isChangePassword) && !token) {
    return NextResponse.redirect(new URL("/login", APP_URL));
  }

  if (isAuth && token) {
    return NextResponse.redirect(new URL("/dashboard", APP_URL));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/login", "/invite/:path*", "/cambiar-contrasena"],
};
