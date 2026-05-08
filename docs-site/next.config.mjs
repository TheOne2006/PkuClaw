import { createMDX } from 'fumadocs-mdx/next';

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  basePath: '/PkuClaw',
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
  reactStrictMode: true,
};

const withMDX = createMDX();

export default withMDX(nextConfig);
