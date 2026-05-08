import Link from 'next/link';
import { GitBranch } from 'lucide-react';
import { PkuClawLogoCard } from '@/components/pkuclaw-logo-card';
import { PkuClawStarfield } from '@/components/pkuclaw-starfield';
import { siteConfig, withBasePath } from '@/lib/layout.shared';

const dialogueExamples = [
  {
    title: 'Check',
    prompt: '帮我看一下这周教学网有什么新东西？',
    response: '已检查教学网：高代新增作业 4，大学英语发布了课堂材料。我把入口和要求整理好了。',
  },
  {
    title: 'Track',
    prompt: '这门课成绩还没出，帮我盯一下。',
    response: '收到。我会在后台跟踪成绩、公告和作业状态；没变化就静默，有更新再告诉你。',
  },
  {
    title: 'Notify',
    prompt: 'DDL 前提醒我，成绩出来也通知。',
    response: '没问题。作业 DDL、成绩更新、课程通知会按你的渠道偏好推送，不把小事刷屏。',
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
          <p className="pkuclaw-hero__eyebrow">PKU STUDY AGENT</p>
          <h1 id="hero-title">PkuClaw</h1>
          <p className="pkuclaw-hero__tagline">
            PKU 学生的一站式教学网 Agent 解决方案
            <br />
            生成笔记，完成作业，通知成绩，DDL提醒...
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

      <section className="pkuclaw-dialogue-grid" aria-label="PkuClaw workflow examples">
        {dialogueExamples.map((example) => (
          <article key={example.title} className="pkuclaw-dialogue-card">
            <div className="pkuclaw-dialogue-card__header">
              <span>{example.title}</span>
              <small>Teaching Web</small>
            </div>
            <div className="pkuclaw-dialogue-card__body">
              <p className="pkuclaw-dialogue-card__bubble pkuclaw-dialogue-card__bubble--user">
                {example.prompt}
              </p>
              <p className="pkuclaw-dialogue-card__bubble pkuclaw-dialogue-card__bubble--agent">
                {example.response}
              </p>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
