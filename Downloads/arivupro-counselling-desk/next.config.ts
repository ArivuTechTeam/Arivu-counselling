import type { NextConfig } from "next";

const isRailway = process.env.RAILWAY === "true";

const nextConfig: NextConfig = {
  output: isRailway ? "standalone" : undefined,
  // On Railway, skip the Cloudflare-specific vite/vinext build
  ...(isRailway && {
    experimental: {
      // Use Node.js runtime for all routes on Railway
    },
  }),
};

export default nextConfig;
