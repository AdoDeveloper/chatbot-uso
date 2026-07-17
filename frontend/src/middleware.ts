import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const token = request.cookies.get("chatbot_access")?.value;
  const { pathname } = request.nextUrl;

  const isAuth = pathname.startsWith("/login") || pathname.startsWith("/invite");
  const isDashboard = pathname.startsWith("/dashboard");
  const isChangePassword = pathname.startsWith("/cambiar-contrasena");

  if ((isDashboard || isChangePassword) && !token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (isAuth && token) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/login", "/invite/:path*", "/cambiar-contrasena"],
};
