import { defineConfig } from "astro/config";

export default defineConfig({
  output: "static",
  server: {
    host: true,
    port: 4321,
  },
  vite: {
    server: {
      proxy: {
        "/api": {
          target: "http://backend:8000",
          changeOrigin: true,
        },
      },
    },
  },
});
