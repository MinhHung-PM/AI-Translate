import type { NextConfig } from "next";

// The browser only ever talks to this Next.js origin. /api/v1/* is proxied
// server-side to the FastAPI backend, so session cookies stay first-party and
// no backend URL or secret is exposed to client bundles (BACKEND_URL is a
// server-only variable — never prefix it with NEXT_PUBLIC_).
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
const isDev = process.env.NODE_ENV !== "production";

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  // OpenAI Realtime: the browser POSTs its WebRTC offer with a short-lived client secret (live captions).
  // Soniox: live audio WebSocket opened with a single-use temporary key.
  "connect-src 'self' https://api.openai.com wss://stt-rt.soniox.com",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  output: "standalone",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(self), display-capture=(self), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
