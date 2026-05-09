'use client';

import { useEffect, useRef } from 'react';

export function PkuClawStarfield() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvasElement = canvasRef.current;
    if (!canvasElement) return;
    const canvas: HTMLCanvasElement = canvasElement;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;
    const context: CanvasRenderingContext2D = ctx;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const pointer = { x: 0, y: 0, active: false };
    let width = 0;
    let height = 0;
    let dpr = 1;
    let particles: Array<{
      x: number;
      y: number;
      vx: number;
      vy: number;
      r: number;
      glow: number;
      phase: number;
    }> = [];
    let meteors: Array<{
      x: number;
      y: number;
      vx: number;
      vy: number;
      length: number;
      life: number;
      maxLife: number;
    }> = [];
    let raf = 0;
    let lastFrameTime = 0;

    const palette = {
      star: '255, 245, 240',
      red: '196, 30, 36',
      gold: '212, 160, 90',
      line: '255, 216, 190',
    };

    const rand = (min: number, max: number) => min + Math.random() * (max - min);

    function particleCount() {
      if (reduceMotion) return 34;
      return Math.min(96, Math.max(52, Math.floor((width * height) / 23500)));
    }

    function createParticle() {
      const speed = reduceMotion ? 0 : rand(0.08, 0.32);
      const angle = rand(0, Math.PI * 2);
      return {
        x: rand(0, width),
        y: rand(0, height),
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
        r: rand(0.7, 1.9),
        glow: rand(0.28, 0.88),
        phase: rand(0, Math.PI * 2),
      };
    }

    function resize() {
      width = window.innerWidth;
      height = window.innerHeight;
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);

      const nextCount = particleCount();
      if (particles.length === 0) {
        particles = Array.from({ length: nextCount }, createParticle);
      } else if (particles.length < nextCount) {
        particles.push(...Array.from({ length: nextCount - particles.length }, createParticle));
      } else if (particles.length > nextCount) {
        particles = particles.slice(0, nextCount);
      }
    }

    function drawLine(
      a: { x: number; y: number },
      b: { x: number; y: number },
      maxDistance: number,
      color: string,
      strength = 1,
    ) {
      const dx = a.x - b.x;
      const dy = a.y - b.y;
      const dist = Math.hypot(dx, dy);
      if (dist > maxDistance) return;
      const alpha = (1 - dist / maxDistance) * strength;
      context.strokeStyle = `rgba(${color}, ${alpha})`;
      context.lineWidth = 0.8;
      context.beginPath();
      context.moveTo(a.x, a.y);
      context.lineTo(b.x, b.y);
      context.stroke();
    }

    function drawParticleLinks(maxDistance: number, color: string, strength: number) {
      const cellSize = maxDistance;
      const grid = new Map<string, number[]>();

      for (let index = 0; index < particles.length; index += 1) {
        const particle = particles[index];
        const key = `${Math.floor(particle.x / cellSize)}:${Math.floor(particle.y / cellSize)}`;
        const bucket = grid.get(key);
        if (bucket) {
          bucket.push(index);
        } else {
          grid.set(key, [index]);
        }
      }

      for (let index = 0; index < particles.length; index += 1) {
        const particle = particles[index];
        const cellX = Math.floor(particle.x / cellSize);
        const cellY = Math.floor(particle.y / cellSize);

        for (let offsetX = -1; offsetX <= 1; offsetX += 1) {
          for (let offsetY = -1; offsetY <= 1; offsetY += 1) {
            const bucket = grid.get(`${cellX + offsetX}:${cellY + offsetY}`);
            if (!bucket) continue;

            for (const otherIndex of bucket) {
              if (otherIndex <= index) continue;
              drawLine(particle, particles[otherIndex], maxDistance, color, strength);
            }
          }
        }
      }
    }

    function spawnMeteor(frameScale: number) {
      if (reduceMotion) return;
      if (meteors.length > 2) return;
      if (Math.random() > Math.min(0.04, 0.012 * frameScale)) return;
      meteors.push({
        x: rand(width * 0.08, width * 0.92),
        y: rand(-40, height * 0.42),
        vx: rand(-7.2, -4.2),
        vy: rand(4.4, 7.2),
        length: rand(120, 210),
        life: 0,
        maxLife: rand(42, 66),
      });
    }

    function drawMeteor(meteor: (typeof meteors)[number], frameScale: number) {
      const alpha = Math.sin((meteor.life / meteor.maxLife) * Math.PI) * 0.75;
      const tailX = meteor.x - meteor.vx * (meteor.length / 10);
      const tailY = meteor.y - meteor.vy * (meteor.length / 10);
      const gradient = context.createLinearGradient(meteor.x, meteor.y, tailX, tailY);
      gradient.addColorStop(0, `rgba(${palette.star}, ${alpha})`);
      gradient.addColorStop(0.34, `rgba(${palette.gold}, ${alpha * 0.54})`);
      gradient.addColorStop(1, 'rgba(255,255,255,0)');
      context.strokeStyle = gradient;
      context.lineWidth = 1.4;
      context.beginPath();
      context.moveTo(meteor.x, meteor.y);
      context.lineTo(tailX, tailY);
      context.stroke();
      meteor.x += meteor.vx * frameScale;
      meteor.y += meteor.vy * frameScale;
      meteor.life += frameScale;
    }

    function draw(time: number) {
      const elapsed = lastFrameTime === 0 ? 1000 / 60 : time - lastFrameTime;
      lastFrameTime = time;
      const frameScale = reduceMotion ? 0 : Math.min(2.4, elapsed / (1000 / 60));

      context.clearRect(0, 0, width, height);
      spawnMeteor(frameScale);

      for (const particle of particles) {
        if (!reduceMotion) {
          particle.x += particle.vx * frameScale;
          particle.y += particle.vy * frameScale;
          if (particle.x < -20) particle.x = width + 20;
          if (particle.x > width + 20) particle.x = -20;
          if (particle.y < -20) particle.y = height + 20;
          if (particle.y > height + 20) particle.y = -20;
        }

        const twinkle = 0.32 + Math.sin(time * 0.0015 + particle.phase) * 0.18 + particle.glow * 0.28;
        const gradient = context.createRadialGradient(
          particle.x,
          particle.y,
          0,
          particle.x,
          particle.y,
          particle.r * 5.5,
        );
        gradient.addColorStop(0, `rgba(${palette.star}, ${twinkle})`);
        gradient.addColorStop(0.55, `rgba(${palette.gold}, ${twinkle * 0.18})`);
        gradient.addColorStop(1, 'rgba(255,255,255,0)');
        context.fillStyle = gradient;
        context.beginPath();
        context.arc(particle.x, particle.y, particle.r * 5.5, 0, Math.PI * 2);
        context.fill();

        context.fillStyle = `rgba(${palette.star}, ${Math.min(0.9, twinkle + 0.2)})`;
        context.beginPath();
        context.arc(particle.x, particle.y, particle.r, 0, Math.PI * 2);
        context.fill();
      }

      drawParticleLinks(118, palette.line, 0.12);

      meteors = meteors.filter((meteor) => meteor.life < meteor.maxLife && meteor.x > -260 && meteor.y < height + 260);
      for (const meteor of meteors) drawMeteor(meteor, frameScale);

      if (pointer.active) {
        const cursor = { x: pointer.x, y: pointer.y };
        const halo = context.createRadialGradient(pointer.x, pointer.y, 0, pointer.x, pointer.y, 220);
        halo.addColorStop(0, `rgba(${palette.red}, 0.18)`);
        halo.addColorStop(0.38, `rgba(${palette.gold}, 0.08)`);
        halo.addColorStop(1, 'rgba(196,30,36,0)');
        context.fillStyle = halo;
        context.beginPath();
        context.arc(pointer.x, pointer.y, 220, 0, Math.PI * 2);
        context.fill();

        for (const particle of particles) {
          drawLine(cursor, particle, 210, palette.gold, 0.48);
        }
      }

      if (!reduceMotion) raf = window.requestAnimationFrame(draw);
    }

    function onPointerMove(event: PointerEvent) {
      pointer.x = event.clientX;
      pointer.y = event.clientY;
      pointer.active = true;
    }

    function onPointerLeave() {
      pointer.active = false;
    }

    resize();
    window.addEventListener('resize', resize, { passive: true });
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerleave', onPointerLeave, { passive: true });
    draw(performance.now());

    return () => {
      window.cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerleave', onPointerLeave);
    };
  }, []);

  return (
    <div className="pkuclaw-starfield" aria-hidden="true">
      <canvas ref={canvasRef} className="pkuclaw-starfield__canvas" />
      <div className="pkuclaw-starfield__glow pkuclaw-starfield__glow--red" />
      <div className="pkuclaw-starfield__glow pkuclaw-starfield__glow--gold" />
      <div className="pkuclaw-starfield__mesh" />
      <svg className="pkuclaw-starfield__lines" viewBox="0 0 1200 700" preserveAspectRatio="none">
        <path d="M80 520 C 250 370, 360 430, 520 250 S 860 120, 1130 260" />
        <path d="M160 170 L 360 250 L 560 130 L 760 300 L 980 210" />
        <path d="M270 610 L 470 430 L 690 500 L 920 350" />
        <circle cx="360" cy="250" r="4" />
        <circle cx="560" cy="130" r="3" />
        <circle cx="760" cy="300" r="4" />
        <circle cx="920" cy="350" r="3" />
      </svg>
    </div>
  );
}
