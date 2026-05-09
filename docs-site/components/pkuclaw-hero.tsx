'use client';

import Link from 'next/link';
import { Code2, GitBranch } from 'lucide-react';
import { motion, useReducedMotion } from 'motion/react';
import { AnimatedChatCard } from '@/components/animated-chat-card';
import { PkuClawLogoCard } from '@/components/pkuclaw-logo-card';
import { PkuClawStarfield } from '@/components/pkuclaw-starfield';
import { siteConfig, withBasePath } from '@/lib/layout.shared';

export function PkuClawHero() {
  const shouldReduceMotion = useReducedMotion();

  const reveal = (delay: number, y = 18, x = 0, scale = 0.96) => ({
    initial: shouldReduceMotion ? { opacity: 1, x: 0, y: 0, scale: 1 } : { opacity: 0, x, y, scale },
    animate: { opacity: 1, x: 0, y: 0, scale: 1 },
    transition: shouldReduceMotion ? { duration: 0 } : { delay, duration: 0.58, ease: 'easeOut' as const },
  });

  return (
    <main className="pkuclaw-home">
      <PkuClawStarfield />
      <motion.nav className="pkuclaw-home__nav" aria-label="PkuClaw" {...reveal(0, -14, 0, 0.98)}>
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
      </motion.nav>

      <section className="pkuclaw-hero" aria-labelledby="hero-title">
        <div className="pkuclaw-hero__copy">
          <motion.p className="pkuclaw-hero__eyebrow" {...reveal(0.12, 18, -18, 0.96)}>
            PKU STUDY AGENT
          </motion.p>
          <motion.h1 id="hero-title" {...reveal(0.22, 24, -26, 0.94)}>
            PkuClaw
          </motion.h1>
          <motion.p className="pkuclaw-hero__tagline" {...reveal(0.34, 20, -18, 0.97)}>
            PKU 学生的一站式教学网 Agent 解决方案
            <br />
            生成笔记，完成作业，通知成绩，DDL提醒...
          </motion.p>
          <div className="pkuclaw-hero__actions">
            <motion.span {...reveal(0.48, 18, -10, 0.95)}>
              <Link href="/docs/user-guide/quickstart" className="pkuclaw-button pkuclaw-button--primary">
                快速开始
              </Link>
            </motion.span>
            <motion.span {...reveal(0.56, 18, -10, 0.95)}>
              <Link href="/docs/developer-guide" className="pkuclaw-button pkuclaw-button--ghost">
                <Code2 aria-hidden="true" size={18} />
                开发者指南
              </Link>
            </motion.span>
            <motion.span {...reveal(0.64, 18, -10, 0.95)}>
              <a href={siteConfig.github} target="_blank" rel="noreferrer" className="pkuclaw-button pkuclaw-button--ghost">
                <GitBranch aria-hidden="true" size={18} />
                GitHub
              </a>
            </motion.span>
          </div>
        </div>

        <motion.div className="pkuclaw-hero__logo-motion" {...reveal(0.32, 28, 34, 0.9)}>
          <PkuClawLogoCard />
        </motion.div>
      </section>

      <AnimatedChatCard />
    </main>
  );
}
