import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

const repository = 'PkuClaw';
const owner = 'TheOne2006';
const githubUrl = `https://github.com/${owner}/${repository}`;

export default defineConfig({
  site: `https://${owner.toLowerCase()}.github.io`,
  base: `/${repository}`,
  integrations: [
    starlight({
      title: 'PkuClaw',
      description: 'PKU workflows study-agent runtime',
      favicon: '/favicon.png',
      locales: {
        root: { label: '简体中文', lang: 'zh-CN' },
      },
      logo: {
        alt: 'PkuClaw',
        light: './src/assets/pkuclaw-icon.png',
        dark: './src/assets/pkuclaw-icon.png',
      },
      customCss: [
        './src/styles/custom.css',
      ],
      head: [
        { tag: 'link', attrs: { rel: 'icon', type: 'image/png', href: '/PkuClaw/favicon.png' } },
        { tag: 'link', attrs: { rel: 'apple-touch-icon', href: '/PkuClaw/icon-192.png' } },
        { tag: 'meta', attrs: { property: 'og:image', content: 'https://theone2006.github.io/PkuClaw/og-image.png' } },
        { tag: 'meta', attrs: { name: 'twitter:image', content: 'https://theone2006.github.io/PkuClaw/og-image.png' } },
      ],
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: githubUrl,
        },
      ],
      editLink: {
        baseUrl: `${githubUrl}/edit/main/docs-site/`,
      },
      sidebar: [
        {
          label: '开始使用',
          items: [
            { slug: 'quickstart' },
            { slug: 'installation' },
            { slug: 'configuration' },
          ],
        },
        {
          label: '运行时',
          items: [
            { slug: 'runtime' },
            { slug: 'quick-actions' },
            { slug: 'skills' },
          ],
        },
        {
          label: '开发者',
          items: [
            { slug: 'architecture' },
            { slug: 'development' },
            { slug: 'contributing' },
          ],
        },
        {
          label: '参考',
          items: [
            { slug: 'reference/config-files' },
            { slug: 'faq' },
          ],
        },
      ],
    }),
  ],
});
