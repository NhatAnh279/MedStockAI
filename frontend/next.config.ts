import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://backend:8000/:path*",
      },
    ];
  },
  experimental: {
    allowedDevOrigins: ["*"],
  },
};

export default nextConfig;
