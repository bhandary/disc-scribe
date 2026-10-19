import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    domains: ["coverartarchive.org", "localhost"],
  },
  experimental: {
    turbo: {},
  },
};

export default nextConfig;
