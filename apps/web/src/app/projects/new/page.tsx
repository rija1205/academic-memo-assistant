"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth/auth-gate";
import { ApiError, createProject, type EducationLevel } from "@/lib/api";

const levels: { value: EducationLevel; label: string }[] = [
  { value: "licence", label: "Licence" },
  { value: "master", label: "Master" },
  { value: "doctorat", label: "Doctorat" },
  { value: "other", label: "Autre" },
];

function lines(value: string): string[] {
  return value.split("\n").map((line) => line.trim()).filter(Boolean);
}

function NewProjectForm() {
  const router = useRouter();
  const [form, setForm] = useState({
    title: "",
    domain: "",
    institution: "",
    education_level: "master" as EducationLevel,
    author_name: "",
    supervisor_name: "",
    academic_year: "",
    thesis_type: "mémoire",
    bibliography_style: "APA 7",
    problem_statement: "",
    general_objective: "",
    specific_objectives: "",
    hypotheses: "",
    keywords: "",
  });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function update(field: keyof typeof form, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      const project = await createProject({
        ...form,
        specific_objectives: lines(form.specific_objectives),
        hypotheses: lines(form.hypotheses),
        keywords: form.keywords.split(",").map((keyword) => keyword.trim()).filter(Boolean),
      });
      router.push(`/projects/${project.id}`);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Création impossible.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="workspace-page-heading">
        <div>
          <p className="eyebrow">Nouveau projet</p>
          <h1>Créer un mémoire</h1>
          <p>Les informations pourront être modifiées à tout moment.</p>
        </div>
      </div>
      <form className="settings-card project-form" onSubmit={handleSubmit}>
        <div className="form-section">
          <h2>Identité du mémoire</h2>
          <div className="form-grid two-columns">
            <label className="auth-field"><span>Titre du mémoire *</span><input required maxLength={500} value={form.title} onChange={(event) => update("title", event.target.value)} /></label>
            <label className="auth-field"><span>Domaine scientifique</span><input maxLength={255} value={form.domain} onChange={(event) => update("domain", event.target.value)} /></label>
            <label className="auth-field"><span>Établissement / université</span><input maxLength={255} value={form.institution} onChange={(event) => update("institution", event.target.value)} /></label>
            <label className="auth-field"><span>Niveau d&apos;étude</span><select value={form.education_level} onChange={(event) => update("education_level", event.target.value)}>{levels.map((level) => <option key={level.value} value={level.value}>{level.label}</option>)}</select></label>
            <label className="auth-field"><span>Auteur</span><input maxLength={200} value={form.author_name} onChange={(event) => update("author_name", event.target.value)} /></label>
            <label className="auth-field"><span>Directeur / encadreur</span><input maxLength={200} value={form.supervisor_name} onChange={(event) => update("supervisor_name", event.target.value)} /></label>
            <label className="auth-field"><span>Année universitaire</span><input maxLength={32} placeholder="2025-2026" value={form.academic_year} onChange={(event) => update("academic_year", event.target.value)} /></label>
            <label className="auth-field"><span>Type de mémoire</span><input maxLength={64} value={form.thesis_type} onChange={(event) => update("thesis_type", event.target.value)} /></label>
            <label className="auth-field"><span>Style bibliographique</span><input maxLength={64} value={form.bibliography_style} onChange={(event) => update("bibliography_style", event.target.value)} /></label>
          </div>
        </div>
        <div className="form-section">
          <h2>Cadre scientifique</h2>
          <label className="auth-field"><span>Problématique</span><textarea rows={4} value={form.problem_statement} onChange={(event) => update("problem_statement", event.target.value)} /></label>
          <label className="auth-field"><span>Objectif général</span><textarea rows={3} value={form.general_objective} onChange={(event) => update("general_objective", event.target.value)} /></label>
          <label className="auth-field"><span>Objectifs spécifiques (une ligne par objectif)</span><textarea rows={4} value={form.specific_objectives} onChange={(event) => update("specific_objectives", event.target.value)} /></label>
          <label className="auth-field"><span>Hypothèses (une ligne par hypothèse)</span><textarea rows={4} value={form.hypotheses} onChange={(event) => update("hypotheses", event.target.value)} /></label>
          <label className="auth-field"><span>Mots-clés (séparés par des virgules)</span><input value={form.keywords} onChange={(event) => update("keywords", event.target.value)} /></label>
        </div>
        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <div className="form-actions"><button className="button button--primary" type="submit" disabled={saving}>{saving ? "Création…" : "Créer le mémoire"}</button></div>
      </form>
    </AppShell>
  );
}

export default function NewProjectPage() {
  return <AuthGate><NewProjectForm /></AuthGate>;
}
