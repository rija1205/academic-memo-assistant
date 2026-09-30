"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { AuthFrame } from "@/components/auth/auth-frame";
import { ApiError, resetPassword } from "@/lib/api";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const value = new URLSearchParams(window.location.search).get("token") ?? "";
    setToken(value);
    window.history.replaceState({}, "", "/reset-password");
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("Les mots de passe ne correspondent pas.");
      return;
    }
    setSubmitting(true);
    try {
      await resetPassword(token, password);
      router.replace("/login?reset=1");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Réinitialisation impossible.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Nouveau mot de passe"
      title="Sécuriser votre accès"
      description="Choisissez un nouveau mot de passe d’au moins 12 caractères."
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <label className="auth-field">
          <span>Jeton de réinitialisation</span>
          <input type="text" value={token} onChange={(event) => setToken(event.target.value)} required />
        </label>
        <label className="auth-field">
          <span>Nouveau mot de passe</span>
          <input type="password" autoComplete="new-password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} required />
        </label>
        <label className="auth-field">
          <span>Confirmation</span>
          <input type="password" autoComplete="new-password" minLength={12} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required />
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="button button--primary auth-submit" type="submit" disabled={submitting || !token}>
          {submitting ? "Enregistrement…" : "Modifier mon mot de passe"}
        </button>
      </form>
      <p className="auth-switch"><Link href="/login">Annuler</Link></p>
    </AuthFrame>
  );
}
