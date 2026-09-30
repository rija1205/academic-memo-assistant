"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { AuthFrame } from "@/components/auth/auth-frame";
import { ApiError, requestPasswordReset } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [resetToken, setResetToken] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setResetToken("");
    setSubmitting(true);
    try {
      const response = await requestPasswordReset(email);
      setMessage(response.message);
      if (response.reset_token) setResetToken(response.reset_token);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Demande impossible.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Récupération"
      title="Retrouver votre compte"
      description="Saisissez votre adresse e-mail. Pour éviter de révéler les comptes existants, la réponse reste la même."
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <label className="auth-field">
          <span>Adresse e-mail</span>
          <input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        {message ? <p className="form-success" role="status">{message}</p> : null}
        <button className="button button--primary auth-submit" type="submit" disabled={submitting}>
          {submitting ? "Envoi…" : "Envoyer les instructions"}
        </button>
      </form>
      {resetToken ? (
        <div className="dev-token">
          <strong>Mode développement</strong>
          <p>Le backend a exposé ce jeton pour les tests locaux :</p>
          <Link href={`/reset-password?token=${encodeURIComponent(resetToken)}`}>Ouvrir la réinitialisation</Link>
        </div>
      ) : null}
      <p className="auth-switch"><Link href="/login">Retour à la connexion</Link></p>
    </AuthFrame>
  );
}
