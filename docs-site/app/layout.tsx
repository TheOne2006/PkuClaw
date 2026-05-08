import type { Metadata, Viewport } from 'next';
import type { ReactNode } from 'react';
import { Provider } from '@/components/provider';
import { siteConfig, withBasePath } from '@/lib/layout.shared';
import './global.css';


export const metadata: Metadata = {
  metadataBase: new URL('https://theone2006.github.io'),
  title: {
    default: 'PkuClaw',
    template: '%s | PkuClaw',
  },
  description: siteConfig.description,
  icons: {
    icon: withBasePath('/favicon.png'),
    apple: withBasePath('/icon-192.png'),
  },
  openGraph: {
    title: 'PkuClaw',
    description: siteConfig.description,
    url: siteConfig.url,
    siteName: 'PkuClaw',
    images: [withBasePath('/og-image.png')],
    locale: 'zh_CN',
    type: 'website',
  },
  twitter: {
    card: 'summary_large_image',
    title: 'PkuClaw',
    description: siteConfig.description,
    images: [withBasePath('/og-image.png')],
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#faf7f4' },
    { media: '(prefers-color-scheme: dark)', color: '#09090b' },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="flex min-h-screen flex-col">
        <Provider>{children}</Provider>
      </body>
    </html>
  );
}
