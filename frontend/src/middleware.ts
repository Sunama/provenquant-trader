import { NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  const key = request.cookies.get("api_key")?.value;
  const isAuthPage = request.nextUrl.pathname === "/auth";

  if (!key && !isAuthPage) {
    return NextResponse.redirect(new URL("/auth", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next|favicon.ico).*)"],
};
