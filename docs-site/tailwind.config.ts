import type { Config } from 'tailwindcss';

const config = {
  content: [
    './app/**/*.{ts,tsx,mdx}',
    './components/**/*.{ts,tsx}',
    './content/**/*.{md,mdx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        pku: {
          red: '#8c1515',
          dark: '#09090b',
          gold: '#d7b56d',
        },
      },
      fontFamily: {
        sans: [
          'var(--font-geist-sans)',
          'Noto Sans SC',
          'PingFang SC',
          'Microsoft YaHei',
          'sans-serif',
        ],
        mono: ['var(--font-geist-mono)', 'SFMono-Regular', 'monospace'],
      },
    },
  },
} satisfies Config;

export default config;
