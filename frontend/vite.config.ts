import { fileURLToPath, URL } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { nitro } from "nitro/vite";

export default defineConfig({
  server: { host: "0.0.0.0", port: 3000, strictPort: true },
  envPrefix: ["VITE_", "NEXT_PUBLIC_"],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  plugins: [
    tailwindcss(),
    tanstackStart(),
    react(),
    nitro({ devProxy: { "/api/**": "http://127.0.0.1:8000" } }),
  ],
  ssr: { noExternal: ["@heroui/react"] },
});
