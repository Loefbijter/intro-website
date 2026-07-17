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
        // Activity images live in Django's media; forward them in dev so
        // relative /media/ URLs from the API resolve (nginx handles this in prod).
        "/media": {
          target: "http://backend:8000",
          changeOrigin: true,
        },
      },
    },
  },
});
