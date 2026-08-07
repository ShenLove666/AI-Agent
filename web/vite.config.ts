import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

function vendorChunk(id: string): string | undefined {
  if (!id.includes("node_modules")) return undefined;
  if (id.includes("@antv") || id.includes("recharts") || id.includes("d3-")) {
    return "vendor-visualization";
  }
  if (id.includes("@radix-ui") || id.includes("lucide-react")) {
    return "vendor-ui";
  }
  if (
    id.includes("react-markdown") ||
    id.includes("react-syntax-highlighter") ||
    id.includes("remark-") ||
    id.includes("rehype-")
  ) {
    return "vendor-markdown";
  }
  if (id.includes("axios") || id.includes("date-fns") || id.includes("zod")) {
    return "vendor-core";
  }
  return undefined;
}

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    rollupOptions: {
      output: {
        manualChunks: vendorChunk
      }
    }
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8081", changeOrigin: true }
    }
  }
});
