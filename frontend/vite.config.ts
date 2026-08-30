import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// 开发时把后端前缀代理到 FastAPI，让前端与后端同源 —— 后端没有 CORS 中间件，
// 同源代理省掉了加它的必要。生产环境由 nginx 做同样的事（见 Dockerfile.frontend）。
const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8001";
const BACKEND_PREFIXES = ["/chat", "/workout", "/documents"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      BACKEND_PREFIXES.map((prefix) => [
        prefix,
        { target: BACKEND, changeOrigin: true },
      ]),
    ),
  },
});
