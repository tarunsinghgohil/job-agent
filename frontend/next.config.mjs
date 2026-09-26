import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

const projectRoot = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  devIndicators: false,
  // Pins the workspace root to this project. Without it, Next.js walks up
  // looking for a lockfile and can land on an unrelated one in the user's
  // home directory, which produces a spurious build warning.
  turbopack: { root: projectRoot },
};

export default nextConfig;
