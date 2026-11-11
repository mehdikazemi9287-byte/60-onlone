/** @type {import('next').NextConfig} */
// Vambi is a front end only. /api/* is proxied to the 60Online ecosystem API (VAMBI_API_ORIGIN, server-side only).
const API_ORIGIN = (process.env.VAMBI_API_ORIGIN ?? "").replace(/\/+$/, "");
const csp = [
  "default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:", "font-src 'self' data:", "connect-src 'self'",
  "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self'",
].join("; ");

const nextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return API_ORIGIN ? [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }] : [];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        { key: "Permissions-Policy", value: "geolocation=(), microphone=(), camera=()" },
        { key: "Content-Security-Policy", value: csp },
      ],
    }];
  },
};
export default nextConfig;
