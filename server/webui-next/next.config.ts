import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  async rewrites() {
    if (!isDev) return [];
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8081/api/:path*",
      },
      // Note: Next.js rewrites may not support raw websockets seamlessly unless handled properly,
      // but standard HTTP polling or API calls will proxy correctly.
    ];
  },
};

export default nextConfig;
