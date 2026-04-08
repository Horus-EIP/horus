import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  /**
   * Skips 308 for page routes. `/api/*` (including `/api/orchestrator/...`) still
   * canonicalizes to no trailing slash, so the web client calls MAS paths without
   * a final `/` to avoid cached 308 + double round-trips.
   */
  skipTrailingSlashRedirect: true,
  /**
   * MAS is reached via `app/api/orchestrator/[[...path]]/route.ts` (server proxy with
   * redirect: "follow") instead of rewrites here — rewrites forward 307 Location:
   * http://mas:8000/... to the browser, which cannot resolve `mas`.
   */
};

export default nextConfig;
