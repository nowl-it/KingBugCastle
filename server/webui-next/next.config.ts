import type { NextConfig } from "next";
import path from "node:path";
import { fileURLToPath } from "node:url";

const isDev = process.env.NODE_ENV === "development";
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

const nextConfig: NextConfig = {
  output: isDev ? undefined : "export",
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  // A pnpm lockfile outside this repository must not make Next trace from the
  // user's home directory.  The static export has no runtime dependency on
  // files outside the repository.
  outputFileTracingRoot: repoRoot,
  // Static export runs on the small operator host too.  The default fan-out (one
  // worker per detected CPU) can exhaust its process limit before page generation.
  experimental: {
    cpus: 1,
    staticGenerationMaxConcurrency: 1,
    staticGenerationMinPagesPerWorker: 25,
  },
  // Rewrites require a running Next server. Production is a static export
  // served directly by dashboard.py/playerportal.py, so declare the proxy only
  // in development instead of returning an unused empty rewrite list at build.
  ...(isDev ? {
    async rewrites() {
      return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8081/api/:path*",
      },
      ];
    },
  } : {}),
};

export default nextConfig;
