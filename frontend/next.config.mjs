/** @type {import('next').NextConfig} */
const nextConfig = {
  // 生产 Docker 部署：输出独立 server.js，无需 node_modules 即可运行
  output: "standalone",
  async rewrites() {
    // 开发环境前端同源代理到 FastAPI（HttpOnly Cookie 可随同源请求携带）
    // Docker 容器内通过 BACKEND_INTERNAL_URL 指向后端服务名
    const backend =
      process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${backend}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
