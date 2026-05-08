import Link from 'next/link';
import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';

export const siteConfig = {
  name: 'PkuClaw',
  description: 'PKU STUDY AGENT',
  url: 'https://theone2006.github.io/PkuClaw',
  basePath: '/PkuClaw',
  github: 'https://github.com/TheOne2006/PkuClaw',
};

export function withBasePath(path: string): string {
  if (path.startsWith('http')) return path;
  return `${siteConfig.basePath}${path.startsWith('/') ? path : `/${path}`}`;
}

function NavTitle() {
  return (
    <Link href="/" className="pkuclaw-nav-title" aria-label="PkuClaw home">
      <img src={withBasePath('/icon-192.png')} alt="" width={28} height={28} />
      <span>PkuClaw</span>
    </Link>
  );
}

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: <NavTitle />,
      url: '/',
      transparentMode: 'top',
    },
    githubUrl: siteConfig.github,
    links: [
      {
        text: '文档',
        url: '/docs',
        active: 'nested-url',
      },
    ],
    searchToggle: {
      enabled: true,
    },
  };
}
