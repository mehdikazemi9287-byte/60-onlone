/** @type {import('next').NextConfig} */
const nextConfig = { distDir: process.env.REVIEW_DIST_DIR || ".next", experimental: {cpus: 1},
  webpack(config) { config.cache = false; return config; },
  async redirects() {
    return [{ source: "/favicon.ico", destination: "/icon.svg", permanent: true }];
  },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "images.unsplash.com" },
      { protocol: "https", hostname: "ui-avatars.com" },
      { protocol: "https", hostname: "upload.wikimedia.org" },
    ],
  },
  async headers() {
    const csp = [
      "default-src 'self'",
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data: https:",
      "font-src 'self' data:",
      "connect-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join("; ");
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "geolocation=(), microphone=(), camera=()",
          },
          { key: "Content-Security-Policy", value: csp },
        ],
      },
      {source:"/admin/content/preview",headers:[{key:"X-Frame-Options",value:"SAMEORIGIN"},{key:"Content-Security-Policy",value:csp.replace("frame-ancestors 'none'","frame-ancestors 'self'")}]} 
    ];
  },
};

export default nextConfig;
