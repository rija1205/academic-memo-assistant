"use client";

import {
  ApiError,
  getAuditReport,
  listAuditTraces,
  runAudit,
  type AuditFinding,
  type AuditReport,
  type AuditSeverity,
  type AuditTrace,
} from "@/lib/api";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

const SEVERITY_ORDER: AuditSeverity[] = ["blocker", "warning", "info"];

const SEVERITY_LABELS: Record<AuditSeverity, string> = {
  blocker: "Bloquant",
  warning: "À vérifier",
  info: "Information",
};

/** Where a finding lives, as a link when the target is a page of the application. */
function locationHref(finding: AuditFinding, projectId: string): string | null {
  if (finding.location_kind === "section" && finding.location_ref) {
    return `/projects/${projectId}?node=${finding.location_ref}`;
  }
  if (finding.location_kind === "reference" && finding.location_ref) {
    return `/projects/${projectId}/bibliography?reference=${finding.location_ref}`;
  }
  return null;
}

function humanMinutes(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return rest ? `${hours} h ${rest}` : `${hours} h`;
}

/**
 * The academic audit panel.
 *
 * Everything shown here comes from the server's deterministic checks. The panel never repairs
 * anything: each finding states what is wrong, where it is and what the author should decide
 * to do. That separation is the whole point of the feature.
 */
export function AuditWorkspace({
  projectId,
  canRun,
}: {
  projectId: string;
  canRun: boolean;
}) {
  const [report, setReport] = useState<AuditReport | null>(null);
  const [traces, setTraces] = useState<AuditTrace[]>([]);
  const [trend, setTrend] = useState<number | null>(null);
  const [severityFilter, setSeverityFilter] = useState<AuditSeverity | "all">("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [nextReport, nextTraces] = await Promise.all([
        getAuditReport(projectId),
        listAuditTraces(projectId).catch(() => ({ items: [], total: 0, blocker_trend: null })),
      ]);
      setReport(nextReport);
      setTraces(nextTraces.items);
      setTrend(nextTraces.blocker_trend);
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Audit indisponible.");
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function run(storeTrace: boolean) {
    setBusy(true);
    setError("");
    try {
      await runAudit(projectId, storeTrace);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Audit impossible.");
    } finally {
      setBusy(false);
    }
  }

  const findings = useMemo(() => {
    if (!report) return [];
    const grouped = new Map<AuditSeverity, AuditFinding[]>();
    for (const severity of SEVERITY_ORDER) {
      grouped.set(
        severity,
        report.findings.filter((finding) => finding.severity === severity),
      );
    }
    return SEVERITY_ORDER.flatMap((severity) => grouped.get(severity) ?? []);
  }, [report]);

  const visible = useMemo(
    () => (severityFilter === "all" ? findings : findings.filter((f) => f.severity === severityFilter)),
    [findings, severityFilter],
  );

  if (error && !report) {
    return <p className="form-error">{error}</p>;
  }
  if (!report) {
    return <p className="empty-panel">Chargement de l&apos;audit…</p>;
  }

  const stats = report.statistics;

  return (
    <div className="audit-workspace">
      <header className="audit-heading">
        <div>
          <p className="eyebrow">Contrôle de cohérence</p>
          <h1>Audit académique</h1>
          <p className="audit-disclaimer">{report.disclaimer}</p>
        </div>
        {canRun ? (
          <div className="audit-actions">
            <button
              className="button button--secondary button--small"
              type="button"
              disabled={busy}
              onClick={() => void run(false)}
            >
              {busy ? "Analyse…" : "Relancer l&apos;audit"}
            </button>
            <button
              className="button button--primary button--small"
              type="button"
              disabled={busy}
              onClick={() => void run(true)}
            >
              Garder une trace
            </button>
          </div>
        ) : null}
      </header>

      <section className={`audit-readiness audit-readiness--${report.readiness.level}`}>
        <strong>{report.readiness.label}</strong>
        <p>{report.readiness.detail}</p>
        <div className="audit-counters">
          {SEVERITY_ORDER.map((severity) => (
            <button
              key={severity}
              type="button"
              className={`audit-counter audit-counter--${severity} ${
                severityFilter === severity ? "selected" : ""
              }`}
              onClick={() => setSeverityFilter(severityFilter === severity ? "all" : severity)}
            >
              <span>{SEVERITY_LABELS[severity]}</span>
              <strong>{report.summary[`${severity}s` as "blockers" | "warnings" | "info"]}</strong>
            </button>
          ))}
        </div>
        <small>
          {report.summary.checks_run} contrôles exécutés
          {report.summary.checks_inconclusive > 0
            ? ` · ${report.summary.checks_inconclusive} non concluants (données insuffisantes)`
            : ""}
        </small>
      </section>

      {error ? <p className="form-error">{error}</p> : null}

      <section className="audit-stats">
        <h2>Statistiques du mémoire</h2>
        <dl>
          <div>
            <dt>Mots</dt>
            <dd>{stats.word_count.toLocaleString("fr-FR")}</dd>
          </div>
          <div>
            <dt>Lecture estimée</dt>
            <dd>{humanMinutes(stats.read_minutes)}</dd>
          </div>
          <div>
            <dt>Sections</dt>
            <dd>
              {stats.section_count}
              {stats.empty_section_count > 0 ? ` · ${stats.empty_section_count} vide(s)` : ""}
            </dd>
          </div>
          <div>
            <dt>Citations</dt>
            <dd>{stats.citation_count}</dd>
          </div>
          <div>
            <dt>Références citées</dt>
            <dd>{stats.distinct_cited_references}</dd>
          </div>
          <div>
            <dt>Non citées</dt>
            <dd>{stats.uncited_reference_count}</dd>
          </div>
          <div>
            <dt>Citations orphelines</dt>
            <dd className={stats.orphan_citation_count > 0 ? "danger" : ""}>
              {stats.orphan_citation_count}
            </dd>
          </div>
          <div>
            <dt>Densité</dt>
            <dd>
              {stats.citation_density === null ? "Non renseigné" : `${stats.citation_density} / 1000 mots`}
            </dd>
          </div>
          <div>
            <dt>Sources indexées</dt>
            <dd>
              {stats.indexed_source_count} / {stats.source_count}
            </dd>
          </div>
          <div>
            <dt>Figures / tableaux</dt>
            <dd>
              {stats.figure_count} / {stats.table_count}
            </dd>
          </div>
          <div>
            <dt>Style</dt>
            <dd>{stats.bibliography_style || "Non renseigné"}</dd>
          </div>
          <div>
            <dt>Années des références</dt>
            <dd>
              {stats.reference_year_span
                ? `${stats.reference_year_span[0]}–${stats.reference_year_span[1]}`
                : "Non renseigné"}
            </dd>
          </div>
        </dl>
        {stats.longest_section ? (
          <p className="audit-longest">
            Section la plus longue : <strong>{stats.longest_section}</strong> (
            {stats.longest_section_words.toLocaleString("fr-FR")} mots).
          </p>
        ) : null}
      </section>

      {report.observations.length > 0 ? (
        <section className="audit-observations">
          <h2>Observations de volume</h2>
          <ul>
            {report.observations.map((observation) => (
              <li key={observation.code}>
                <strong>{observation.label}</strong> — {observation.detail}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="audit-findings">
        <h2>Points à traiter ({visible.length})</h2>
        {visible.length === 0 ? (
          <p className="empty-panel">
            Aucun point à ce niveau de gravité. L&apos;audit automatique ne remplace pas votre
            relecture.
          </p>
        ) : null}
        {visible.map((finding) => {
          const href = locationHref(finding, projectId);
          return (
            <article
              key={`${finding.code}-${finding.location_ref ?? "x"}`}
              className={`audit-finding audit-finding--${finding.severity}`}
            >
              <header>
                <span className="audit-severity">{SEVERITY_LABELS[finding.severity]}</span>
                <strong>{finding.title}</strong>
                {finding.location_label ? <code>{finding.location_label}</code> : null}
                {finding.count > 1 ? <em>×{finding.count}</em> : null}
              </header>
              <p>{finding.detail}</p>
              {finding.remedy ? (
                <p className="audit-remedy">
                  <span>À faire :</span> {finding.remedy}
                </p>
              ) : null}
              {href ? (
                <Link className="audit-link" href={href}>
                  Aller voir
                </Link>
              ) : null}
            </article>
          );
        })}
      </section>

      <section className="audit-checklist">
        <h2>Préparation de la soutenance</h2>
        <p className="audit-hint">
          Liste de questions à traiter par vous-même. L&apos;audit ne modifie rien et ne rédige
          rien à votre place.
        </p>
        <ol>
          {report.defence_checklist.map((item, index) => (
            <li key={`${item.priority}-${index}`} className={`audit-step audit-step--${item.priority}`}>
              <span className="audit-step-category">{item.category}</span>
              <div>
                <strong>{item.question}</strong>
                {item.evidence ? <small>{item.evidence}</small> : null}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {traces.length > 0 ? (
        <section className="audit-traces">
          <h2>Historique des audits</h2>
          {trend !== null ? (
            <p className="audit-trend">
              {trend > 0
                ? `${trend} point(s) bloquant(s) de moins que lors du premier audit.`
                : trend < 0
                  ? `${Math.abs(trend)} point(s) bloquant(s) de plus que lors du premier audit.`
                  : "Le nombre de points bloquants n'a pas changé."}
            </p>
          ) : null}
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Bloquants</th>
                <th>À vérifier</th>
                <th>Informations</th>
                <th>Mots</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((trace) => (
                <tr key={trace.id}>
                  <td>{new Date(trace.created_at).toLocaleString("fr-FR")}</td>
                  <td className={trace.blocker_count > 0 ? "danger" : ""}>{trace.blocker_count}</td>
                  <td>{trace.warning_count}</td>
                  <td>{trace.info_count}</td>
                  <td>{trace.word_count.toLocaleString("fr-FR")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      <section className="audit-checks">
        <h2>Contrôles exécutés</h2>
        <ul>
          {report.checks.map((check) => (
            <li key={check.code}>
              <code>{check.code}</code>
              {check.skipped_reason ? (
                <span className="audit-inconclusive">Source insuffisante : {check.skipped_reason}</span>
              ) : (
                <span>{check.finding_count} constat(s)</span>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
