import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import fs from 'fs';
import path from 'path';

const DATA_DIR = path.join(process.cwd(), 'data');

function dataPlugin() {
  return {
    name: 'serve-data',

    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        // Strip base path so this works in both dev and preview
        const base = '/wc2026brief';
        const url = req.url?.startsWith(base) ? req.url.slice(base.length) : req.url;
        const match = url?.match(/^\/data\/([^/]+\.json)$/);
        if (match) {
          const file = path.join(DATA_DIR, match[1]);
          if (fs.existsSync(file)) {
            res.setHeader('Content-Type', 'application/json');
            res.end(fs.readFileSync(file));
            return;
          }
        }
        next();
      });
    },

    closeBundle() {
      const dest = path.join(process.cwd(), 'dist', 'data');
      fs.mkdirSync(dest, { recursive: true });
      for (const file of fs.readdirSync(DATA_DIR)) {
        if (file.endsWith('.json')) {
          fs.copyFileSync(path.join(DATA_DIR, file), path.join(dest, file));
        }
      }
    },
  };
}

export default defineConfig({
  plugins: [svelte(), dataPlugin()],
  base: '/wc2026brief/',
});
