import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api 代理到 CS2HQ 后端 8101；公网隧道放行 trycloudflare（沿用 MindVault 模式）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8101",
        changeOrigin: true,
      },
    },
    allowedHosts: [".trycloudflare.com", ".kumshing.dev"],
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
