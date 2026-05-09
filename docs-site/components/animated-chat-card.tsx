'use client';

import { useRef } from 'react';
import { BellRing, FileText, SearchCheck } from 'lucide-react';
import { motion, useInView, useReducedMotion } from 'motion/react';
import { withBasePath } from '@/lib/layout.shared';

const userAvatar = withBasePath('/user-avatar.png');
const botAvatar = withBasePath('/pkuclaw-bot-avatar.png');
const notesPdf = withBasePath('/files/note.pdf');

type ChatMessage = {
  id: string;
  side: 'left' | 'right';
  tone: 'user' | 'notes' | 'topics' | 'notify';
  avatar: string;
  label: string;
  text?: string;
  paragraphs?: string[];
  bullets?: string[];
  checks?: string[];
  topics?: Array<{
    title: string;
    description: string;
  }>;
  attachment?: {
    name: string;
    meta: string;
    href: string;
  };
};

type WorkflowCard = {
  id: string;
  eyebrow: string;
  title: string;
  icon: typeof FileText;
  tone: 'notes' | 'topics' | 'notify';
  messages: ChatMessage[];
};

const workflowCards: WorkflowCard[] = [
  {
    id: 'notes',
    eyebrow: 'Notes delivery',
    title: '整理课堂笔记',
    icon: FileText,
    tone: 'notes',
    messages: [
      {
        id: 'notes-user',
        side: 'right',
        tone: 'user',
        avatar: userAvatar,
        label: 'Student',
        text: '请给我整理中国经济专题的笔记，然后发送给我。',
      },
      {
        id: 'notes-agent',
        side: 'left',
        tone: 'notes',
        avatar: botAvatar,
        label: 'Agent',
        paragraphs: ['已整理并发送给你了：'],
        bullets: [
          '中国经济专题完整笔记 PDF（Lecture 1–8，125 页）',
          '汇总 Markdown 笔记 + note.pdf 已放入 outbox',
          '覆盖绪论、农村改革、人口劳动力、土地城市化等专题……',
        ],
        checks: [
          'PDF 编译成功',
          '57 张图示已补入',
          '未发现缺失图片引用……',
        ],
        attachment: {
          name: 'note.pdf',
          meta: 'Lecture 1–8 · 125 pages',
          href: notesPdf,
        },
      },
    ],
  },
  {
    id: 'topics',
    eyebrow: 'Teaching Web',
    title: '查询课程信息',
    icon: SearchCheck,
    tone: 'topics',
    messages: [
      {
        id: 'topics-user-1',
        side: 'right',
        tone: 'user',
        avatar: userAvatar,
        label: 'Student',
        text: '看看多智能体基础的个人课题有哪些。',
      },
      {
        id: 'topics-agent-1',
        side: 'left',
        tone: 'topics',
        avatar: botAvatar,
        label: 'Agent',
        paragraphs: ['教学网里“多智能体基础”的 教学内容 → 个人课题 目录下目前有：'],
        bullets: [
          '个人课题1–6',
          '辅助文件：latex 模板、评分细则',
          '现在看到的是目录；我可以继续打开附件汇总具体题目……',
        ],
      },
      {
        id: 'topics-user-2',
        side: 'right',
        tone: 'user',
        avatar: userAvatar,
        label: 'Student',
        text: '具体告诉我都是什么课题。',
      },
      {
        id: 'topics-agent-2',
        side: 'left',
        tone: 'topics',
        avatar: botAvatar,
        label: 'Agent',
        paragraphs: ['我看了 6 个附件，具体课题是：'],
        topics: [
          {
            title: '课题1 / 4',
            description: '无线资源共享、零和矩阵博弈与 Hedge，偏理论推导。',
          },
          {
            title: '课题2 / 5',
            description: '无人机集群对抗、原子拥塞博弈，理论 + 仿真适中。',
          },
          {
            title: '课题3 / 6',
            description: 'MiniGrid 强化学习、CFR Poker，编程/实验较重……',
          },
        ],
        bullets: ['如果要选题，我可以按数学推导量、代码量和风险继续排序。'],
      },
    ],
  },
  {
    id: 'notify',
    eyebrow: 'Loop with signal',
    title: '汇总DDL与通知',
    icon: BellRing,
    tone: 'notify',
    messages: [
      {
        id: 'notify-user',
        side: 'right',
        tone: 'user',
        avatar: userAvatar,
        label: 'Student',
        text: '最近有什么重要的通知或者 DDL 吗？',
      },
      {
        id: 'notify-agent',
        side: 'left',
        tone: 'notify',
        avatar: botAvatar,
        label: 'Agent',
        paragraphs: ['有，当前最值得处理的是两项：'],
        bullets: [
          '算法设计与分析：第五次作业，5 月 11 日 23:59 截止，未提交，需上传 PDF。优先级最高。',
          '中国经济专题：第二次读书笔记，5 月 27 日 23:59 截止，未提交，提交窗口已开放。',
          '已提交事项已折叠：NLP Assignment 2、第一次读书笔记等……',
        ],
        checks: ['已过滤已提交事项', '已按 DDL 和优先级排序', '建议先处理算法第五次作业'],
      },
    ],
  },
];

function MessageContent({ message }: { message: ChatMessage }) {
  return (
    <>
      <span>{message.label}</span>
      {message.text ? <p>{message.text}</p> : null}
      {message.paragraphs?.map((paragraph) => (
        <p key={paragraph}>{paragraph}</p>
      ))}
      {message.topics ? (
        <div className="pkuclaw-chat-topic-list">
          {message.topics.map((topic) => (
            <p key={topic.title}>
              <strong>{topic.title}：</strong>
              {topic.description}
            </p>
          ))}
        </div>
      ) : null}
      {message.bullets ? (
        <ul>
          {message.bullets.map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      ) : null}
      {message.checks ? (
        <div className="pkuclaw-chat-checks">
          <strong>已完成检查</strong>
          <ul>
            {message.checks.map((check) => (
              <li key={check}>{check}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {message.attachment ? (
        <a
          className="pkuclaw-chat-attachment"
          href={message.attachment.href}
          target="_blank"
          rel="noreferrer"
          aria-label={`Open ${message.attachment.name}`}
        >
          <span aria-hidden="true">PDF</span>
          <div>
            <strong>{message.attachment.name}</strong>
            <small>{message.attachment.meta}</small>
          </div>
        </a>
      ) : null}
    </>
  );
}

export function AnimatedChatCard() {
  const ref = useRef<HTMLElement>(null);
  const isInView = useInView(ref, {
    amount: 0.2,
    margin: '0px 0px -12% 0px',
    once: true,
  });
  const shouldReduceMotion = useReducedMotion();
  const shouldShow = shouldReduceMotion || isInView;

  return (
    <section ref={ref} className="pkuclaw-chat-showcase" aria-label="PkuClaw live workflow examples">
      <div className="pkuclaw-chat-grid">
        {workflowCards.map((card, cardIndex) => {
          const CardIcon = card.icon;

          const cardDelay = shouldReduceMotion ? 0 : cardIndex * 0.14;

          return (
            <motion.article
              key={card.id}
              className="pkuclaw-chat-card"
              data-tone={card.tone}
              initial={{ opacity: shouldReduceMotion ? 1 : 0, y: shouldReduceMotion ? 0 : 28, scale: shouldReduceMotion ? 1 : 0.965 }}
              animate={
                shouldShow
                  ? { opacity: 1, y: 0, scale: 1 }
                  : { opacity: shouldReduceMotion ? 1 : 0, y: shouldReduceMotion ? 0 : 28, scale: shouldReduceMotion ? 1 : 0.965 }
              }
              transition={{ delay: cardDelay, duration: 0.48, ease: 'easeOut' }}
            >
              <div className="pkuclaw-chat-card__shine" aria-hidden="true" />
              <div className="pkuclaw-chat-card__header">
                <div className="pkuclaw-chat-card__icon" aria-hidden="true">
                  <CardIcon size={19} strokeWidth={2.35} />
                </div>
                <div>
                  <p>{card.eyebrow}</p>
                  <h3>{card.title}</h3>
                </div>
              </div>

              <div className="pkuclaw-chat-card__messages">
                {card.messages.map((message, messageIndex) => {
                  const itemDelay = shouldReduceMotion ? 0 : cardDelay + 0.2 + messageIndex * 0.24;
                  const fromX = message.side === 'left' ? -20 : 20;

                  return (
                    <div
                      key={message.id}
                      className="pkuclaw-chat-message"
                      data-side={message.side}
                      data-tone={message.tone}
                    >
                      <motion.div
                        className="pkuclaw-chat-message__avatar"
                        initial={{ opacity: 0, scale: 0.72 }}
                        animate={shouldShow ? { opacity: 1, scale: 1 } : { opacity: 0, scale: 0.72 }}
                        transition={{ delay: itemDelay, duration: 0.3, ease: 'easeOut' }}
                        aria-hidden="true"
                      >
                        <img src={message.avatar} alt="" width={44} height={44} />
                      </motion.div>
                      <motion.div
                        className="pkuclaw-chat-message__bubble"
                        initial={{ opacity: 0, x: fromX, y: 8, scale: 0.98 }}
                        animate={
                          shouldShow
                            ? { opacity: 1, x: 0, y: 0, scale: 1 }
                            : { opacity: 0, x: fromX, y: 8, scale: 0.98 }
                        }
                        transition={{ delay: itemDelay + 0.08, duration: 0.4, ease: 'easeOut' }}
                      >
                        <MessageContent message={message} />
                      </motion.div>
                    </div>
                  );
                })}
              </div>
            </motion.article>
          );
        })}
      </div>
    </section>
  );
}
