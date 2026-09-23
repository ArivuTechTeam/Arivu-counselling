function requiredValue(name) {
  const value = process.env[name]?.trim();
  if (!value || /^(replace_with_|your-|your_)/i.test(value)) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

function requiredUrl(name) {
  const value = requiredValue(name);
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute URL.`);
  }
  const local = ["localhost", "127.0.0.1"].includes(parsed.hostname);
  if (process.env.VERCEL_ENV === "production" && local) {
    throw new Error(`${name} must not use localhost in a production deployment.`);
  }
  if (parsed.protocol !== "https:" && !(local && parsed.protocol === "http:")) {
    throw new Error(`${name} must use HTTPS outside localhost development.`);
  }
  return parsed;
}

const supabaseUrl = requiredUrl("NEXT_PUBLIC_SUPABASE_URL");
const apiUrl = requiredUrl("NEXT_PUBLIC_API_BASE_URL");
requiredValue("NEXT_PUBLIC_SUPABASE_ANON_KEY");
const tenantId = requiredValue("NEXT_PUBLIC_DEFAULT_TENANT_ID");
if (!/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(tenantId)) {
  throw new Error("NEXT_PUBLIC_DEFAULT_TENANT_ID must be a UUID.");
}
const websocketOrigin = `${supabaseUrl.protocol === "https:" ? "wss:" : "ws:"}//${supabaseUrl.host}`;
const developmentScripts = process.env.NODE_ENV === "development" ? " 'unsafe-eval'" : "";
const contentSecurityPolicy = [
  "default-src 'self'",
  // @react-pdf/renderer uses Yoga's WebAssembly build in the browser. CSP3's
  // narrow `wasm-unsafe-eval` source permits WebAssembly compilation without
  // granting the broader JavaScript `unsafe-eval` permission in production.
  `script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'${developmentScripts}`,
  "style-src 'self' 'unsafe-inline'",
  // Extracted figure PNGs are served from private Supabase Storage via signed
  // URLs, so the storage origin must be allowed for <img> (connect-src already
  // permits it for other calls).
  `img-src 'self' data: blob: ${supabaseUrl.origin}`,
  "font-src 'self' data:",
  `connect-src 'self' ${supabaseUrl.origin} ${websocketOrigin} ${apiUrl.origin}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=()",
  },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
