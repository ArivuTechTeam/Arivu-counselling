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

requiredUrl("NEXT_PUBLIC_SUPABASE_URL");
requiredUrl("NEXT_PUBLIC_API_BASE_URL");
requiredValue("NEXT_PUBLIC_SUPABASE_ANON_KEY");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  {
    key: "Strict-Transport-Security",
    value: "max-age=31536000; includeSubDomains",
  },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=()",
  },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
