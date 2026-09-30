"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth/auth-gate";
import { ApiError, listSessions, revokeSession, type SessionSummary } from "@/lib/api";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function SettingsContent() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    void listSessions().then(setSessions).catch((cause) => {
      setError(cause instanceof ApiError ? cause.message : "Sessions indisponibles.");
    });
  }, []);

  async function handleRevoke(session: SessionSummary) {
    try {
      await revokeSession(session.id);
      if (session.current) {
        window.location.assign("/login");
        return;
      }
      setSessions((current) => current.filter((item) => item.id !== session.id));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Révoquer impossible.");
    }
  }

  return (
    <AppShell>
      <div className="workspace-page-heading">
        <div>
          <p className="eyebrow">Préférences</p>
          <h1>Paramètres</h1>
          <p>Les réglages d’intégration et de récupération seront complétés dans les étapes suivantes.</p>
        </div>
      </div>
      <section className="settings-card">
        <h2>Sécurité</h2>
        <div className="settings-row"><div><strong>Session actuelle</strong><p>Les sessions sont stockées côté serveur et protégées par cookie HttpOnly.</p></div><span className="verified-badge">Activée</span></div>
        <div className="settings-row"><div><strong>Google OAuth</strong><p>La connexion Google est disponible lorsqu’elle est configurée sur le serveur.</p></div><span className="module-status">Configuration serveur</span></div>
      </section>
      <section className="settings-card">
        <h2>Sessions actives</h2>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {!sessions.length && !error ? <p className="muted-copy">Aucune session supplémentaire.</p> : null}
        <div className="session-list">
          {sessions.map((session) => (
            <div className="settings-row" key={session.id}>
              <div><strong>{session.current ? "Session actuelle" : "Autre session"}</strong><p>{session.user_agent || "Appareil inconnu"} · vue {formatDate(session.last_seen_at)}</p></div>
              <button className="button button--secondary button--small" type="button" onClick={() => void handleRevoke(session)}>Révoquer</button>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}

export default function SettingsPage() {
  return (
    <AuthGate>
      <SettingsContent />
    </AuthGate>
  );
}
