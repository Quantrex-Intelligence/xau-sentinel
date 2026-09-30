import type { NextConfig } from "next";

// Where the Next.js server forwards /api/* and /ws/* so the browser only ever
// talks to its own origin. 127.0.0.1 (not "localhost") because localhost can
// resolve to IPv6 first while the API listens on IPv4. Rewrites are compiled
// at build time, so Docker passes API_PROXY_TARGET as a build arg.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_PROXY_TARGET}/api/:path*` },
      { source: "/ws/:path*", destination: `${API_PROXY_TARGET}/ws/:path*` },
    ];
  },
};

export default nextConfig;
