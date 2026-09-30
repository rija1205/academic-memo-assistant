"use client";

import { FormEvent, useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth/auth-gate";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, updateProfile } from "@/lib/api";

function ProfileContent() {
  const { user, refresh } = useAuth();
  const [displayName, setDisplayName] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDisplayName(user?.display_name ?? "");
  }, [user?.display_name]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setSaving(true);
    try {
      await updateProfile(displayName || null);
      await refresh();
      setMessage("Profil mis à jour.");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Mise à jour impossible.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="workspace-page-heading">
        <div>
          <p className="eyebrow">Compte utilisateur</p>
          <h1>Mon profil</h1>
          <p>Ces informations sont visibles uniquement dans votre espace.</p>
        </div>
      </div>
      <section className="settings-card profile-card">
        <div className="profile-avatar">{(user?.display_name || user?.email || "?").slice(0, 1).toUpperCase()}</div>
        <div>
          <h2>{user?.display_name || "Utilisateur"}</h2>
          <p>{user?.email}</p>
          <span className="verified-badge">{user?.email_verified ? "E-mail vérifié" : "E-mail non vérifié"}</span>
        </div>
      </section>
      <form className="settings-card profile-form" onSubmit={handleSubmit}>
        <h2>Modifier le nom affiché</h2>
        <label className="auth-field">
          <span>Nom</span>
          <input type="text" maxLength={200} value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {message ? <p className="form-success" role="status">{message}</p> : null}
        <button className="button button--primary" type="submit" disabled={saving}>{saving ? "Enregistrement…" : "Enregistrer"}</button>
      </form>
    </AppShell>
  );
}

export default function ProfilePage() {
  return (
    <AuthGate>
      <ProfileContent />
    </AuthGate>
  );
}
