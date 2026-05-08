import { withBasePath } from '@/lib/layout.shared';

export function PkuClawLogoCard() {
  return (
    <div className="pkuclaw-logo-card" aria-label="PkuClaw icon badge">
      <div className="pkuclaw-logo-card__orbit" />
      <div className="pkuclaw-logo-card__inner">
        <img src={withBasePath('/icon-512.png')} alt="PkuClaw icon" width={150} height={150} />
        <div>
          <p>Runtime surface</p>
          <strong>Realtime · Loop · Outbox</strong>
        </div>
      </div>
    </div>
  );
}
