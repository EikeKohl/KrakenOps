import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  // Self-contained server bundle for Docker image. Next emits .next/standalone
  // with only the runtime files needed; the dashboard Dockerfile copies that
  // and starts it with `node server.js`.
  output: "standalone",
};

export default nextConfig;
