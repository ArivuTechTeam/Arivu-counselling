import { defineConfig } from "@railway/config";

export default defineConfig({
  services: {
    "arivupro-counselling": {
      build: {
        builder: "DOCKERFILE",
        dockerfilePath: "Dockerfile",
      },
      deploy: {
        startCommand: "sh -c 'node scripts/migrate-railway.mjs && node server.js'",
        healthcheckPath: "/",
        restartPolicyType: "ON_FAILURE",
        restartPolicyMaxRetries: 3,
      },
    },
  },
});
