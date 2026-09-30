"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AuthFrame } from "@/components/auth/auth-frame";
import { useAuth } from "@/components/auth/auth-provider";
import { ApiError } from "@/lib/api";

function RegisterForm() {
  const router = useRouter();
  const { register, loading } = useAuth();
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await register(email, password, displayName || undefined);
      router.replace("/dashboard");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Inscription impossible.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthFrame
      eyebrow="Créer votre espace"
      title="Commencer votre mémoire"
      description="Votre compte protège vos projets, vos sources et votre historique."
    >
      <form className="auth-form" onSubmit={handleSubmit}>
        <label className="auth-field">
          <span>Nom (facultatif)</span>
          <input type="text" autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
        </label>
        <label className="auth-field">
          <span>Adresse e-mail</span>
          <input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label className="auth-field">
          <span>Mot de passe</span>
          <input type="password" autoComplete="new-password" minLength={12} value={password} onChange={(event) => setPassword(event.target.value)} required />
          <small>12 caractères minimum. Utilisez une phrase unique.</small>
        </label>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <button className="button button--primary auth-submit" type="submit" disabled={submitting || loading}>
          {submitting ? "Création…" : "Créer mon compte"}
        </button>
      </form>
      <p className="auth-switch">Déjà inscrit ? <Link href="/login">Se connecter</Link></p>
    </AuthFrame>
  );
}

export default function RegisterPage() {
  return <RegisterForm />;
}
