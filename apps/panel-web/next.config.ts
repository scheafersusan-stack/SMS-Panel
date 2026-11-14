import type { NextConfig } from "next";

// Static export: no server features. `make web-ci` produces dist/index.html.
const config: NextConfig = {
  output: "export",
  distDir: "dist",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  // The type gate is `npm run typecheck`, run before every build.
  typescript: { ignoreBuildErrors: true },
  productionBrowserSourceMaps: false,
  poweredByHeader: false,
};

export default config;
