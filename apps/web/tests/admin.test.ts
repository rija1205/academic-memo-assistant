import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getHealthDetails,
  getMetrics,
  getPlatformStats,
  listAdminActions,
  listAdminUsers,
  listSecurityEvents,
  setUserAdministrator,
  setUserSuspension,
  type AdminUser,
  type ObservabilitySnapshot,
  type PlatformStats,
} from "@/lib/api";

const USER: AdminUser = {
  user_id: "user-1",
  email: "rakoto@example.org",
  display_name: "Rakoto Marie",
  is_active: true,
  is_admin: false,
  is_suspended: false,
  suspended_at: null,
  suspended_reason: null,
  created_at: "2026-01-02T10:00:00Z",
  last_login_at: "2026-10-27T08:00:00Z",
  project_count: 3,
  owned_project_count: 1,
};

const STATS: PlatformStats = {
  users: 12,
  suspended_users: 1,
  administrators: 1,
  projects: 34,
  archived_projects: 2,
  sources: 140,
  citations: 210,
  exports: 18,
  audits: 6,
  blockers_open: 2,
};

const METRICS: ObservabilitySnapshot = {
  version: "0.1.0",
  scope: "process",
  warning: "Metriques par processus.",
  started_at: "2026-10-28T08:00:00Z",
  uptime_seconds: 3600,
  requests: { total: 1200, by_route: { "/api/projects": 400 }, errors_5xx: 3, rate_limited: 7 },
  latency_ms: { count: 100, p50: 12, p95: 48 },
  by_route: {},
  security_events: { permission_denied: 2 },
  exports: { pdf: 12, docx: 6 },
  llm: { calls: 30, tokens: 45000 },
  rag_queries: 15,
};

function jsonMock(payload: unknown, status = 200) {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (status === 204) return new Response(null, { status });
    const body = url.includes("/auth/csrf") ? { csrf_token: "token" } : payload;
    return new Response(JSON.stringify(body), { status });
  });
  vi.stubGlobal("fetch", mock);
  vi.stubGlobal("document", { cookie: "ama_csrf=test-token" });
  return mock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("administration client", () => {
  it("lists accounts with a search", async () => {
    const mock = jsonMock({ items: [USER], total: 1, limit: 50, offset: 0 });
    const result = await listAdminUsers("rakoto", true);
    const url = String(mock.mock.calls.at(-1)?.[0]);
    expect(url).toContain("/api/admin/users?");
    expect(url).toContain("query=rakoto");
    expect(url).toContain("only_suspended=true");
    expect(result.items[0].email).toBe("rakoto@example.org");
  });

  it("returns platform statistics as counts only", async () => {
    const mock = jsonMock(STATS);
    const stats = await getPlatformStats();
    expect(mock.mock.calls.at(-1)?.[0]).toBe("/api/backend/api/admin/stats");
    expect(stats.users).toBe(12);
    expect(stats.blockers_open).toBe(2);
    // No memoir content travels in a platform statistic.
    for (const value of Object.values(stats)) {
      expect(typeof value).toBe("number");
    }
  });

  it("suspends an account with a reason", async () => {
    const mock = jsonMock({ ...USER, is_suspended: true, suspended_reason: "Fraude" });
    await setUserSuspension("user-1", true, "Fraude");
    const call = mock.mock.calls.at(-1) as [string, RequestInit];
    expect(call[0]).toContain("/api/admin/users/user-1/suspension");
    expect(call[0]).toContain("suspended=true");
    expect(call[0]).toContain("reason=Fraude");
    expect(call[1].method).toBe("POST");
  });

  it("reinstates an account", async () => {
    const mock = jsonMock(USER);
    await setUserSuspension("user-1", false);
    expect(String(mock.mock.calls.at(-1)?.[0])).toContain("suspended=false");
  });

  it("grants and revokes the administrator flag", async () => {
    const mock = jsonMock({ ...USER, is_admin: true });
    await setUserAdministrator("user-1", true);
    expect(String(mock.mock.calls.at(-1)?.[0])).toContain("is_admin=true");
  });

  it("lists the administrator actions", async () => {
    const mock = jsonMock({
      items: [
        {
          id: "a1",
          actor_id: "admin-1",
          target_user_id: "user-2",
          action: "suspend",
          target: "x@example.org",
          reason: "Fraude",
          outcome: "success",
          created_at: "2026-10-28T09:00:00Z",
        },
      ],
    });
    const result = await listAdminActions();
    expect(mock.mock.calls.at(-1)?.[0]).toBe("/api/backend/api/admin/admin-actions");
    expect(result.items[0].action).toBe("suspend");
  });
});

describe("observability client", () => {
  it("reads the metrics and states the scope", async () => {
    const mock = jsonMock(METRICS);
    const metrics = await getMetrics();
    expect(mock.mock.calls.at(-1)?.[0]).toBe("/api/backend/api/observability/metrics");
    expect(metrics.scope).toBe("process");
    expect(metrics.requests.errors_5xx).toBe(3);
    expect(metrics.llm.tokens).toBe(45000);
  });

  it("reads the dependency health", async () => {
    jsonMock({
      status: "degraded",
      dependencies: { postgres: "ok", redis: "unavailable" },
      version: "0.1.0",
      environment: "production",
    });
    const health = await getHealthDetails();
    expect(health.dependencies.redis).toBe("unavailable");
  });

  it("reads the security events with a filter", async () => {
    const mock = jsonMock({ items: [], total: 0 });
    await listSecurityEvents("permission_denied", 24);
    const url = String(mock.mock.calls.at(-1)?.[0]);
    expect(url).toContain("kind=permission_denied");
    expect(url).toContain("since_hours=24");
  });
});
