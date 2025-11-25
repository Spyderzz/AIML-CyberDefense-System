import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const isGitHub = process.env.GH_PAGES === "true";

export default defineConfig({
  base: isGitHub ? "/AIML-CyberDefense-System/" : "/",

  plugins: [react()],

  // Local Dev Server Settings
  server: {
    port: 3000,
    proxy: {
      "/auth": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
        secure: false
      },
      "/api": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
        secure: false,
        rewrite: (p) => p.replace(/^\/api/, "")
      },
      "/predict_flow": {
        target: "http://127.0.0.1:5000",
        changeOrigin: true,
        secure: false
      },
      "/socket.io": {
        target: "http://127.0.0.1:5000",
        ws: true,
        changeOrigin: true,
        secure: false
      }
    }
  },


  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 2000
  },

  preview: {
    port: 4173
  }
});
