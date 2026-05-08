const stars = [
  ['8%', '18%', '1.8s'],
  ['16%', '62%', '2.4s'],
  ['24%', '34%', '2.1s'],
  ['30%', '78%', '2.8s'],
  ['38%', '22%', '1.9s'],
  ['45%', '55%', '2.7s'],
  ['52%', '14%', '2.2s'],
  ['58%', '72%', '3.1s'],
  ['64%', '38%', '2.5s'],
  ['71%', '18%', '2.9s'],
  ['78%', '64%', '2.3s'],
  ['84%', '28%', '3.2s'],
  ['91%', '48%', '2.6s'],
  ['96%', '12%', '3.4s'],
];

export function PkuClawStarfield() {
  return (
    <div className="pkuclaw-starfield" aria-hidden="true">
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
      {stars.map(([x, y, delay], index) => (
        <span
          key={`${x}-${y}`}
          className="pkuclaw-starfield__star"
          style={{
            '--x': x,
            '--y': y,
            '--delay': delay,
          } as React.CSSProperties}
        />
      ))}
    </div>
  );
}
