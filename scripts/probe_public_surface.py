"""Executable security probe for the surface that must never be publicly reachable.

These are real HTTP calls against the application, not source inspection. The point is to
confirm that the protection is *enforced* rather than merely declared: an endpoint that
depends on a dependency it never calls looks identical to a protected one when read.

The requests are expected to be refused. A test that passes because the endpoint answered
200 would be worse than useless, so the assertions are on the refusal.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

# The budget guard is disabled so that the token check is what is being observed. Left
# enabled, an unreachable Redis makes the guard fail closed with a 503 before the endpoint is
# reached, and every route would "refuse" for the wrong reason: the probe would pass while
# proving nothing about authorisation.
os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ["SOURCE_PROCESSING_MODE"] = "async"
os.environ["SOURCE_WORKER_TOKEN"] = os.environ.get(
    "SOURCE_WORKER_TOKEN", "jeton-de-sondeuse-a-ne-pas-utiliser"
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

#: Endpoints that exist for the worker and for operators, never for the public. Each one is
#: expected to refuse an anonymous caller.
FORBIDDEN_WITHOUT_CREDENTIALS = [
    ("POST", "/api/internal/sources/00000000-0000-0000-0000-000000000001/process"),
    ("POST", "/api/internal/sources/00000000-0000-0000-0000-000000000001/fail"),
    ("POST", "/api/internal/rag/sources/00000000-0000-0000-0000-000000000001/index"),
    ("POST", "/api/internal/rag/sources/00000000-0000-0000-0000-000000000001/deindex"),
    ("GET", "/api/internal/rag/config"),
    ("GET", "/api/admin/stats"),
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/admin-actions"),
    ("POST", "/api/admin/users/00000000-0000-0000-0000-000000000001/suspension"),
    # Reading metrics is anonymous on purpose: a scraper has no session. Resetting them is
    # not, because it would let anyone erase the operator's view of the system.
    ("POST", "/api/observability/metrics/reset"),
    ("GET", "/api/observability/security-events"),
]

#: The subset guarded by the worker token, re-probed with a valid token to show that the
#: refusal above is an authorisation decision and not an unrelated crash.
WORKER_ROUTES = [entry for entry in FORBIDDEN_WITHOUT_CREDENTIALS if "/internal/" in entry[1]]

#: Endpoints that are public by design, listed so the probe cannot be mistaken for a claim
#: that the whole observability surface is closed. Metrics counters and the dependency health
#: report are what a container orchestrator polls; if this project ever decides otherwise, the
#: assertion below fails loudly instead of the exposure going unnoticed.
PUBLIC_BY_DESIGN = [
    ("GET", "/api/observability/metrics"),
    ("GET", "/api/observability/health/details"),
    ("GET", "/health/live"),
    ("GET", "/"),
]

#: Refusals that are acceptable for an unauthenticated caller.
REFUSALS = {401, 403, 404, 405}


def main() -> int:
    client = TestClient(app, raise_server_exceptions=False)
    problems: list[str] = []

    print("Routes qui doivent refuser un appel anonyme")
    print(f"{'methode':<7} {'code':>5}  route")
    print("-" * 74)
    for method, path in FORBIDDEN_WITHOUT_CREDENTIALS:
        response = client.request(method, path)
        code = response.status_code
        if code not in REFUSALS:
            problems.append(f"{method} {path} a repondu {code} au lieu d'un refus")
        print(f"{method:<7} {code:>5}  {path}   [{'refus' if code in REFUSALS else 'EXPOSE'}]")

    print()
    print("Routes publiques par conception (verification de l'intention)")
    print(f"{'methode':<7} {'code':>5}  route")
    print("-" * 74)
    for method, path in PUBLIC_BY_DESIGN:
        response = client.request(method, path)
        code = response.status_code
        expected = code in (200, 503)
        if not expected:
            problems.append(
                f"{method} {path} a repondu {code} ; une route publique par conception "
                "doit repondre 200, ou 503 quand une dependance manque"
            )
        verdict = "public" if expected else "INATTENDU"
        print(f"{method:<7} {code:>5}  {path}   [{verdict}]")

    # Proving the refusal comes from the authorisation check and not from an unrelated
    # failure: a valid token must get past the same routes. A 401 on both would be
    # indistinguishable from a route that is simply broken.
    print()
    print("Controle : un jeton valide franchit la meme porte")
    print(f"{'methode':<7} {'code':>5}  route")
    print("-" * 74)
    for method, path in WORKER_ROUTES:
        response = client.request(
            method, path, headers={"X-Worker-Token": os.environ["SOURCE_WORKER_TOKEN"]}
        )
        code = response.status_code
        # 200 or a data-level failure both prove the guard was passed; 401 would not.
        if code in REFUSALS:
            problems.append(
                f"{method} {path} refuse encore un jeton valide ({code}) : "
                "la porte refuse pour une autre raison que l'absence de jeton"
            )
        print(f"{method:<7} {code:>5}  {path}   [{'passe' if code not in REFUSALS else 'REFUSE'}]")

    print("-" * 74)
    if problems:
        print("Ecarts detectes :")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"{len(FORBIDDEN_WITHOUT_CREDENTIALS)} routes protegees, "
        f"{len(PUBLIC_BY_DESIGN)} routes publiques conformes a l'intention."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
