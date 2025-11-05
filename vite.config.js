import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// НИКАКОЙ кастомной base — оставь по умолчанию
export default defineConfig({
  plugins: [react()]
});
