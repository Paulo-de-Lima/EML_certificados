import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // `npm run dev` fora do Docker: repassa /api para a API em localhost:8000.
    proxy: { "/api": "http://localhost:8000" },
  },
});
