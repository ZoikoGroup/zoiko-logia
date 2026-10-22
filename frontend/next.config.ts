import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Keep production previews separate from the running development server.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  devIndicators: false,
};

export default nextConfig;
