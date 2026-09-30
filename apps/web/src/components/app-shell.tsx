"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@/components/auth/auth-provider";

const navigation = [
  { href: "/dashboard", label: "Mes mémoires" },
  { href: "/projects/new", label: "Nouveau mémoire" },
  { href: "/dashboard?module=sources", label: "Mes sources", soon: true },
  { href: "/dashboard?module=library", label: "Bibliothèque", soon: true },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();

  return (
    <div className="workspace-shell">
      <aside className="workspace-sidebar">
        <Link href="/dashboard" className="workspace-brand">
          <span className="brand-mark" aria-hidden="true"><span /><span /><span /></span>
          <span>Academic Memo<br />Assistant</span>
        </Link>
        <p className="sidebar-caption">Espace de travail</p>
        <nav className="workspace-nav" aria-label="Navigation principale">
          {navigation.map((item) => (
            <Link
              href={item.href}
              key={item.label}
              className={`workspace-nav-item ${pathname === item.href ? "active" : ""}`}
            >
              <span>{item.label}</span>
              {item.soon ? <small>bientôt</small> : null}
            </Link>
          ))}
        </nav>
        <div className="workspace-sidebar-bottom">
          <Link href="/profile" className={`workspace-nav-item ${pathname === "/profile" ? "active" : ""}`}>
            <span>Profil</span>
          </Link>
          <Link href="/settings" className={`workspace-nav-item ${pathname === "/settings" ? "active" : ""}`}>
            <span>Paramètres</span>
          </Link>
          <button className="workspace-nav-item workspace-logout" type="button" onClick={() => void logout()}>
            <span>Déconnexion</span>
          </button>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="workspace-header">
          <div>
            <p className="workspace-kicker">Mon espace académique</p>
            <strong>Bonjour {user?.display_name || user?.email}</strong>
          </div>
          <span className="workspace-secure">Session sécurisée</span>
        </header>
        <main className="workspace-content">{children}</main>
      </div>
    </div>
  );
}
