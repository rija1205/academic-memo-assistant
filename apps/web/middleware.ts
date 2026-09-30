import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const protectedPrefixes = ["/dashboard", "/profile", "/settings", "/projects"];
const sessionCookieName = process.env.NEXT_PUBLIC_SESSION_COOKIE_NAME ?? "ama_session";

export function middleware(request: NextRequest) {
  const hasSessionCookie = Boolean(request.cookies.get(sessionCookieName)?.value);
  const isProtected = protectedPrefixes.some(
    (prefix) => request.nextUrl.pathname === prefix || request.nextUrl.pathname.startsWith(`${prefix}/`),
  );

  if (isProtected && !hasSessionCookie) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/profile/:path*", "/settings/:path*", "/projects/:path*"],
};
