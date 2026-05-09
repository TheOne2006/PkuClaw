import Link from 'next/link';
import { Code2, GitBranch } from 'lucide-react';
import type { CSSProperties } from 'react';
import { AnimatedChatCard } from '@/components/animated-chat-card';
import { PkuClawLogoCard } from '@/components/pkuclaw-logo-card';
import { PkuClawStarfield } from '@/components/pkuclaw-starfield';
import { siteConfig, withBasePath } from '@/lib/layout.shared';

function revealStyle(delayMs: number, y = 18, x = 0, scale = 0.96): CSSProperties {
  return {
    '--pkuclaw-reveal-delay': `${delayMs}ms`,
    '--pkuclaw-reveal-x': `${x}px`,
    '--pkuclaw-reveal-y': `${y}px`,
    '--pkuclaw-reveal-scale': scale,
  } as CSSProperties;
}

export function PkuClawHero() {
  return (
    <main className="pkuclaw-home">
      <PkuClawStarfield />
      <nav className="pkuclaw-home__nav pkuclaw-reveal" aria-label="PkuClaw" style={revealStyle(0, -14, 0, 0.98)}>
        <Link href="/" className="pkuclaw-home__brand">
          <span className="pkuclaw-home__brand-mark"><img src={withBasePath('/icon-192.png')} alt="" width={32} height={32} /></span>
          <span>PkuClaw</span>
        </Link>
        <div className="pkuclaw-home__nav-links">
          <Link href="/docs">Docs</Link>
          <a href={siteConfig.github} target="_blank" rel="noreferrer">
            GitHub
          </a>
        </div>
      </nav>

      <section className="pkuclaw-hero" aria-labelledby="hero-title">
        <div className="pkuclaw-hero__copy">
          <p className="pkuclaw-hero__eyebrow pkuclaw-reveal" style={revealStyle(120, 18, -18, 0.96)}>
            PKU STUDY AGENT
          </p>
          <h1 id="hero-title" className="pkuclaw-reveal" style={revealStyle(220, 24, -26, 0.94)}>
            PkuClaw
          </h1>
          <p className="pkuclaw-hero__tagline pkuclaw-reveal" style={revealStyle(340, 20, -18, 0.97)}>
            PKU 学生的一站式教学网 Agent 解决方案
            <br />
            生成笔记，完成作业，通知成绩，DDL提醒...
          </p>
          <div className="pkuclaw-hero__actions">
            <span className="pkuclaw-reveal" style={revealStyle(480, 18, -10, 0.95)}>
              <Link href="/docs/user-guide/quickstart" className="pkuclaw-button pkuclaw-button--primary">
                快速开始
              </Link>
            </span>
            <span className="pkuclaw-reveal" style={revealStyle(560, 18, -10, 0.95)}>
              <Link href="/docs/developer-guide" className="pkuclaw-button pkuclaw-button--ghost">
                <Code2 aria-hidden="true" size={18} />
                开发者指南
              </Link>
            </span>
            <span className="pkuclaw-reveal" style={revealStyle(640, 18, -10, 0.95)}>
              <a href={siteConfig.github} target="_blank" rel="noreferrer" className="pkuclaw-button pkuclaw-button--ghost">
                <GitBranch aria-hidden="true" size={18} />
                GitHub
              </a>
            </span>
          </div>
        </div>

        <div className="pkuclaw-hero__logo-motion pkuclaw-reveal" style={revealStyle(320, 28, 34, 0.9)}>
          <PkuClawLogoCard />
        </div>
      </section>

      <AnimatedChatCard />
    </main>
  );
}
