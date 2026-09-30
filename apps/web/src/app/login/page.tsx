"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { AuthFrame } from "@/components/auth/auth-frame";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError, getGoogleStatus, getSafeNext, redirectToGoogle } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const { user, loading, login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    const next = getSafeNext(new URLSearchParams(window.location.search).get("next"));
    if (!loading && user) router.replace(next);
    void getGoogleStatus().then(setGoogleEnabled).catch(() => setGoogleEnabled(false));
  }, [loading, router, user]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await login(email, password);
      const next = getSafeNext(new URLSearchParams(window.location.search).get("next"));
      router.replace(next);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Connexion impossible.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Espace sécurisé"
      title="Ravi de vous revoir"
      description="Connectez-vous pour retrouver vos mémoires et vos sources."
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <label className="auth-field">
          <span>Adresse e-mail</span>
          <input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label className="auth-field">
          <span>Mot de passe</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="button button--primary auth-submit" type="submit" disabled={submitting || loading}>
          {submitting ? "Connexion…" : "Se connecter"}
        </button>
      </form>
      <div className="auth-divider"><span>ou</span></div>
      <button className="button auth-google" type="button" disabled={!googleEnabled} onClick={() => void redirectToGoogle(getSafeNext(new URLSearchParams(window.location.search).get("next")))}>
        <span aria-hidden="true">G</span>
        {googleEnabled ? "Continuer avec Google" : "Google OAuth non configuré"}
      </button>
      <p className="auth-switch">
        Pas encore de compte ? <Link href="/register">Créer un compte</Link>
      </p>
      <p className="auth-switch"><Link href="/forgot-password">Mot de passe oublié ?</Link></p>
    </AuthFrame>
  );
}

export default function LoginPage() {
  return <LoginForm />;
}
