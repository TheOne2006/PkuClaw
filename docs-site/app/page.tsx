import type { Metadata } from 'next';
import { PkuClawHero } from '@/components/pkuclaw-hero';

export const metadata: Metadata = {
  title: 'PkuClaw',
  description: 'PKU STUDY AGENT：PKU 学生的一站式教学网 Agent 解决方案。',
};

export default function HomePage() {
  return <PkuClawHero />;
}
