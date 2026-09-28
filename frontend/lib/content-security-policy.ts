type ContentSecurityPolicyOptions = {
  nonce: string;
  supabaseOrigin: string;
  apiOrigin: string;
  development?: boolean;
};

/** Build the per-request CSP used by middleware and browser security tests. */
export function buildContentSecurityPolicy({
  nonce,
  supabaseOrigin,
  apiOrigin,
  development = false,
}: ContentSecurityPolicyOptions): string {
  const websocketUrl = new URL(supabaseOrigin);
  websocketUrl.protocol = websocketUrl.protocol === "https:" ? "wss:" : "ws:";
  const websocketOrigin = websocketUrl.origin;
  const developmentScripts = development ? " 'unsafe-eval'" : "";
  const productionUpgrade = development ? "" : "; upgrade-insecure-requests";

  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' 'wasm-unsafe-eval'${developmentScripts}`,
    // React components use inline style attributes for tenant colours and
    // charts. Script execution is nonce-protected independently.
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${supabaseOrigin}`,
    "font-src 'self' data:",
    `connect-src 'self' ${supabaseOrigin} ${websocketOrigin} ${apiOrigin}`,
    "worker-src 'self' blob:",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ") + productionUpgrade;
}
