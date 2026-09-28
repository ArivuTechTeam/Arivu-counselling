import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { buildContentSecurityPolicy } from "@/lib/content-security-policy";

function requiredOrigin(name: string, value: string | undefined): string {
  if (!value) throw new Error(`Missing required public environment variable: ${name}`);
  return new URL(value).origin;
}

const supabaseOrigin = requiredOrigin(
  "NEXT_PUBLIC_SUPABASE_URL",
  process.env.NEXT_PUBLIC_SUPABASE_URL,
);
const apiOrigin = requiredOrigin(
  "NEXT_PUBLIC_API_BASE_URL",
  process.env.NEXT_PUBLIC_API_BASE_URL,
);

export function middleware(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const policy = buildContentSecurityPolicy({
    nonce,
    supabaseOrigin,
    apiOrigin,
    development: process.env.NODE_ENV === "development",
  });
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", policy);

  const response = NextResponse.next({
    request: { headers: requestHeaders },
  });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  // Prefetch and navigation responses need the same request-specific nonce as
  // direct page loads, so only immutable assets bypass the middleware.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
