import type { Metadata } from 'next';
import { PkuClawHero } from '@/components/pkuclaw-hero';

export const metadata: Metadata = {
  title: 'PkuClaw',
  description: 'PKU study-agent runtime，把实时消息、后台检查、运行时配置和渠道通知收束成轻量 workflow。',
};

export default function HomePage() {
  return <PkuClawHero />;
}
