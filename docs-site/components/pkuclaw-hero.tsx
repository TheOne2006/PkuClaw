import Link from 'next/link';
import { GitBranch, Radio, Repeat2, Settings2 } from 'lucide-react';
import { PkuClawLogoCard } from '@/components/pkuclaw-logo-card';
import { PkuClawStarfield } from '@/components/pkuclaw-starfield';
import { siteConfig, withBasePath } from '@/lib/layout.shared';

const features = [
  {
    icon: Radio,
    title: 'Realtime first',
    description: '用户消息和 quick action 保持即时、清晰、可流式回复。',
  },
  {
    icon: Repeat2,
    title: 'Loop with signal',
    description: '后台检查默认静默，只有重要变化才进入通知链路。',
  },
  {
    icon: Settings2,
    title: 'Runtime as files',
    description: '配置、prompts、skills 都落在文件系统，方便审计和 review。',
  },
];

export function PkuClawHero() {
  return (
    <main className="pkuclaw-home">
      <PkuClawStarfield />
      <nav className="pkuclaw-home__nav" aria-label="PkuClaw">
        <Link href="/" className="pkuclaw-home__brand">
          <span className="pkuclaw-home__brand-mark"><img src={withBasePath('/icon-192.png')} alt="" width={32} height={32} /></span>
          <span>PkuClaw</span>
        </Link>
        <div className="pkuclaw-home__nav-links">
          <Link href="/docs/">Docs</Link>
          <a href={siteConfig.github} target="_blank" rel="noreferrer">
            GitHub
          </a>
        </div>
      </nav>

      <section className="pkuclaw-hero" aria-labelledby="hero-title">
        <div className="pkuclaw-hero__copy">
          <p className="pkuclaw-hero__eyebrow">PKU study-agent runtime</p>
          <h1 id="hero-title">PkuClaw</h1>
          <p className="pkuclaw-hero__tagline">
            把实时消息、后台检查、运行时配置和渠道通知
            <br />
            收束成轻量、可配置、可扩展的 workflow。
          </p>
          <div className="pkuclaw-hero__actions">
            <Link href="/docs/quickstart/" className="pkuclaw-button pkuclaw-button--primary">
              快速开始
            </Link>
            <a href={siteConfig.github} target="_blank" rel="noreferrer" className="pkuclaw-button pkuclaw-button--ghost">
              <GitBranch aria-hidden="true" size={18} />
              GitHub
            </a>
          </div>
        </div>

        <PkuClawLogoCard />
      </section>

      <section className="pkuclaw-feature-grid" aria-label="PkuClaw features">
        {features.map((feature) => {
          const Icon = feature.icon;
          return (
            <article key={feature.title} className="pkuclaw-feature-card">
              <Icon aria-hidden="true" size={22} />
              <h2>{feature.title}</h2>
              <p>{feature.description}</p>
            </article>
          );
        })}
      </section>
    </main>
  );
}
