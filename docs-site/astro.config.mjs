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
      logo: {
        alt: 'PkuClaw',
        light: './src/assets/pkuclaw-logo-light.svg',
        dark: './src/assets/pkuclaw-logo-dark.svg',
      },
      customCss: ['./src/styles/custom.css'],
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
