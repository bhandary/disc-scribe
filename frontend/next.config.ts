import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The runner stage copies .next/standalone and starts its server.js.
  output: "standalone",
  images: {
    domains: ["coverartarchive.org", "localhost"],
  },
};

export default nextConfig;
