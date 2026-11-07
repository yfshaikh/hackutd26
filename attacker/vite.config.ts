import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Port 5180 so it sits beside the defender console (5173). 5174 belongs to another project.
export default defineConfig({
  plugins: [react()],
  server: { port: 5180, strictPort: true },
});
