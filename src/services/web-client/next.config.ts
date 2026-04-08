import type { NextConfig } from "next";

const orchestratorTarget = (
  process.env.ORCHESTRATOR_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/orchestrator/:path*",
        destination: `${orchestratorTarget}/:path*`,
      },
    ];
  },
};

export default nextConfig;
