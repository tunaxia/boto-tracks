// @ts-check
import { defineConfig } from 'astro/config';

import tailwindcss from '@tailwindcss/vite';

import cloudflare from '@astrojs/cloudflare';
import sitemap from '@astrojs/sitemap';
import alpinejs from '@astrojs/alpinejs';

// https://astro.build/config
export default defineConfig({
  site: 'https://boto-tracks.tunaxia.com/',

  vite: {
    plugins: [tailwindcss()]
  },

  adapter: cloudflare(),
  integrations: [sitemap(), alpinejs()]
});