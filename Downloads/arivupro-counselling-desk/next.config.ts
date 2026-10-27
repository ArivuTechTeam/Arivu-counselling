import type { NextConfig } from "next";

const isRailway = process.env.RAILWAY === "true";

const nextConfig: NextConfig = {
  output: isRailway ? "standalone" : undefined,
  typescript: { ignoreBuildErrors: true },
  eslint: { ignoreDuringBuilds: true },
  ...(isRailway && {
    serverExternalPackages: ["better-sqlite3"],
  }),
};

export default nextConfig;
