"use client";

import {
  ApiError,
  getMetrics,
  getPlatformStats,
  listAdminActions,
  listAdminUsers,
  listSecurityEvents,
  setUserAdministrator,
  setUserSuspension,
  type AdminUser,
} from "@/lib/api";
import { useCallback, useEffect, useState } from "react";

/**
 * The platform administration console.
 *
 * It manages **accounts**, not memoirs. There is deliberately no way to read a memoir from
 * here: an administrator can suspend an account, and the project permissions still decide who
 * may open a memoir. Every action is recorded server-side in the administrator audit trail.
 */
export function AdminWorkspace() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Record<string, number> | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [actions, setActions] = useState<{ id: string; action: string; target: string | null; created_at: string | null }[]>([]);
  const [events, setEvents] = useState<{ id: string; kind: string; outcome: string; created_at: string | null }[]>([]);
  const [query, setQuery] = useState("");
  const [onlySuspended, setOnlySuspended] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    try {
      const [list, platform, snapshot, adminActions, securityEvents] = await Promise.all([
        listAdminUsers(query || undefined, onlySuspended),
        getPlatformStats(),
        getMetrics().catch(() => null),
        listAdminActions().catch(() => ({ items: [] })),
        listSecurityEvents().catch(() => ({ items: [], total: 0 })),
      ]);
      setUsers(list.items);
      setTotal(list.total);
      setStats(platform as unknown as Record<string, number>);
      setMetrics(snapshot as unknown as Record<string, unknown> | null);
      setActions(adminActions.items);
      setEvents(securityEvents.items.slice(0, 20));
      setError("");
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Administration indisponible.");
    }
  }, [onlySuspended, query]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(message);
      await load();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Action impossible.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="admin-workspace">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h1>Comptes et plateforme</h1>
          <p className="admin-hint">
            Cette console gère les comptes. Elle ne donne accès à aucun mémoire : les
            permissions de projet continuent de s&apos;appliquer.
          </p>
        </div>
        <button
          className="button button--secondary button--small"
          type="button"
          disabled={busy}
          onClick={() => void load()}
        >
          Actualiser
        </button>
      </header>

      {error ? <p className="form-error">{error}</p> : null}
      {notice ? <p className="admin-notice">{notice}</p> : null}

      {stats ? (
        <dl className="admin-stats">
          {(
            [
              ["users", "Comptes"],
              ["suspended_users", "Suspendus"],
              ["administrators", "Administrateurs"],
              ["projects", "Mémoires"],
              ["sources", "Sources"],
              ["citations", "Citations"],
              ["exports", "Exports"],
              ["audits", "Audits"],
            ] as const
          ).map(([key, label]) => (
            <div key={key}>
              <dt>{label}</dt>
              <dd>{stats[key] ?? 0}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {metrics ? (
        <section className="admin-metrics">
          <h2>Activité du processus</h2>
          <p className="admin-hint">{String(metrics.warning ?? "")}</p>
          <dl>
            <div>
              <dt>Requêtes</dt>
              <dd>{String((metrics.requests as Record<string, number>)?.total ?? 0)}</dd>
            </div>
            <div>
              <dt>Erreurs 5xx</dt>
              <dd className="danger">{String((metrics.requests as Record<string, number>)?.errors_5xx ?? 0)}</dd>
            </div>
            <div>
              <dt>Limites atteintes</dt>
              <dd>{String((metrics.requests as Record<string, number>)?.rate_limited ?? 0)}</dd>
            </div>
            <div>
              <dt>Latence p95</dt>
              <dd>{String((metrics.latency_ms as Record<string, number>)?.p95 ?? "—")} ms</dd>
            </div>
            <div>
              <dt>Appels modèle</dt>
              <dd>{String((metrics.llm as Record<string, number>)?.calls ?? 0)}</dd>
            </div>
            <div>
              <dt>Requêtes RAG</dt>
              <dd>{String(metrics.rag_queries ?? 0)}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      <section className="admin-users">
        <h2>Comptes ({total})</h2>
        <div className="admin-toolbar">
          <input
            aria-label="Rechercher un compte"
            placeholder="Rechercher par adresse ou nom…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <label>
            <input
              type="checkbox"
              checked={onlySuspended}
              onChange={(event) => setOnlySuspended(event.target.checked)}
            />
            <span>Suspendus seulement</span>
          </label>
        </div>
        <table>
          <thead>
            <tr>
              <th>Compte</th>
              <th>Mémoires</th>
              <th>État</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.user_id}>
                <td>
                  <strong>{user.email}</strong>
                  <small>
                    {user.display_name ?? "—"} · inscrit le{" "}
                    {user.created_at ? new Date(user.created_at).toLocaleDateString("fr-FR") : "—"}
                  </small>
                </td>
                <td>
                  {user.project_count} dont {user.owned_project_count} comme propriétaire
                </td>
                <td>
                  {user.is_suspended ? (
                    <span className="danger">Suspendu</span>
                  ) : user.is_active ? (
                    "Actif"
                  ) : (
                    "Désactivé"
                  )}
                  {user.is_admin ? " · administrateur" : ""}
                </td>
                <td className="admin-row-actions">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void act(
                        () => setUserSuspension(user.user_id, !user.is_suspended, user.is_suspended ? undefined : "Suspension depuis la console"),
                        user.is_suspended ? "Compte réintégré." : "Compte suspendu.",
                      )
                    }
                  >
                    {user.is_suspended ? "Réintégrer" : "Suspendre"}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void act(
                        () => setUserAdministrator(user.user_id, !user.is_admin),
                        user.is_admin ? "Privilèges retirés." : "Privilèges accordés.",
                      )
                    }
                  >
                    {user.is_admin ? "Retirer admin" : "Accorder admin"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="admin-trails">
        <div>
          <h2>Actions administratives</h2>
          <ul>
            {actions.length === 0 ? <li className="admin-hint">Aucune action enregistrée.</li> : null}
            {actions.map((action) => (
              <li key={action.id}>
                <code>{action.action}</code> {action.target ?? ""}
                <small>{action.created_at ? new Date(action.created_at).toLocaleString("fr-FR") : ""}</small>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h2>Événements de sécurité</h2>
          <ul>
            {events.length === 0 ? <li className="admin-hint">Aucun événement récent.</li> : null}
            {events.map((event) => (
              <li key={event.id}>
                <code>{event.kind}</code> <span className="admin-outcome">{event.outcome}</span>
                <small>{event.created_at ? new Date(event.created_at).toLocaleString("fr-FR") : ""}</small>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
