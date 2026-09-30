import Link from "next/link";
import type { ReactNode } from "react";

export function AuthFrame({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <div className="auth-shell">
      <header className="auth-topbar">
        <Link href="/" className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <span>
            Academic Memo Assistant
            <small>ThesisFlow visual identity</small>
          </span>
        </Link>
        <Link href="/" className="auth-back-link">
          Retour à l’accueil
        </Link>
      </header>
      <main className="auth-container">
        <section className="auth-card" aria-labelledby="auth-title">
          <p className="eyebrow">{eyebrow}</p>
          <h1 id="auth-title">{title}</h1>
          <p className="auth-description">{description}</p>
          {children}
        </section>
      </main>
    </div>
  );
}
