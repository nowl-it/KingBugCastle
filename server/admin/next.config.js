/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://localhost:8080/admin/api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
