import type { NextConfig } from "next";

// Fully static: pages are generated at build time from the verified JSON in ../../data (no server, no secrets).
const config: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  trailingSlash: true,
  reactStrictMode: true,
};

export default config;
