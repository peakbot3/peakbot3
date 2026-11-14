// Protective browser headers added to every response from the site.
// The editor preview shows the site in a frame, so only Lovable's own pages may frame it.
const FRAME_ANCESTORS = "'self' https://lovable.dev https://*.lovable.dev https://*.lovable.app https://*.lovableproject.com";

export function securityHeaders(url: URL, forwardedProto: string | null): Record<string, string> {
  const https = url.protocol === "https:" || (forwardedProto ?? "").split(",")[0]?.trim() === "https";
  const csp = [`base-uri 'self'`, `object-src 'none'`, `frame-ancestors ${FRAME_ANCESTORS}`];
  if (https) csp.push("upgrade-insecure-requests");
  const out: Record<string, string> = {
    "Content-Security-Policy": csp.join("; "),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin-allow-popups",
    "X-Permitted-Cross-Domain-Policies": "none",
  };
  if (https) out["Strict-Transport-Security"] = "max-age=31536000";
  return out;
}

/** Private answers (sign-in, dashboard data, bot sync) must never be stored by browsers or shared caches. */
export function isPrivatePath(pathname: string) {
  return pathname.startsWith("/api/") || pathname.startsWith("/_serverFn");
}

export function withSecurityHeaders(request: Request, response: Response): Response {
  if (response.status === 101) return response;
  const url = new URL(request.url);
  const headers = new Headers(response.headers);
  for (const [k, v] of Object.entries(securityHeaders(url, request.headers.get("x-forwarded-proto")))) {
    if (!headers.has(k)) headers.set(k, v);
  }
  if (isPrivatePath(url.pathname)) headers.set("Cache-Control", "no-store");
  headers.delete("x-powered-by");
  headers.delete("server");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}
