/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  serverExternalPackages: ["sharp"],
  experimental: {
    serverActions: { allowedOrigins: ["*"] },
  },
};

export default nextConfig;
