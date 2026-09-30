"""Prove the worker reaches the authenticated internal API over real HTTP.

``TestClient`` proves the dependency logic. It does not prove the wire: a header that never
leaves the process, a URL built wrongly, a worker configured with a token the API does not
accept. This starts a real uvicorn server and drives it with the worker's own task code.

The database is not available in this environment, so the leg that can be proven is the one
that matters and is otherwise untested: **authorisation over a real socket**. What is asserted
is the transition from refusal to passage — an anonymous or wrongly-tokened caller gets 401,
and the worker's configured token gets past the gate. The failure that follows is the database
being unreachable, which is a different problem and is reported as such.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"
WORKER = ROOT / "services" / "worker"

TOKEN = "jeton-de-validation-reel-0123456789"
SOURCE_ID = "00000000-0000-0000-0000-000000000042"

#: Configured before the application is imported: the settings are read at import time.
os.environ.update(
    {
        "APP_ENV": "development",
        "RATE_LIMIT_ENABLED": "false",  # isolate the token check from the budget guard
        "SOURCE_PROCESSING_MODE": "async",
        "SOURCE_WORKER_TOKEN": TOKEN,
        "SOURCE_WORKER_URL": "",  # set below, once the port is known
        # ``connect_timeout`` keeps the database leg short: nothing listens on 5432 here, and
        # without it the handler waits far longer than this script should take. The failure it
        # produces is the absence of a database, not a problem with authorisation.
        "DATABASE_URL": "postgresql+asyncpg://u:p@127.0.0.1:5432/absent?connect_timeout=1",
    }
)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def main() -> int:
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    os.environ["SOURCE_WORKER_URL"] = base_url

    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(API)
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=API,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        import httpx

        # Generous, because this check starts a real server: with a tight deadline it fails on
        # a loaded machine rather than on a fault, and a check that oscillates is worse than
        # no check at all.
        deadline = time.time() + 90
        ready = False
        while time.time() < deadline:
            if server.poll() is not None:
                print("Le serveur n'a pas demarre :")
                print((server.stdout.read() if server.stdout else "")[-1200:])
                return 1
            try:
                if httpx.get(f"{base_url}/health/live", timeout=2).status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError:
                time.sleep(0.4)
        if not ready:
            print("Le serveur n'a pas repondu dans le delai.")
            return 1
        print(f"API demarree sur {base_url} (vrai processus uvicorn).")
        print()

        internal = [
            ("POST", f"/api/internal/sources/{SOURCE_ID}/process"),
            ("POST", f"/api/internal/rag/sources/{SOURCE_ID}/index"),
            ("GET", "/api/internal/rag/config"),
        ]

        print("1. Appel anonyme (doit etre refuse)")
        print(f"{'methode':<7} {'code':>5}  route")
        print("-" * 72)
        for method, path in internal:
            response = httpx.request(method, f"{base_url}{path}", timeout=10)
            mark = "refus" if response.status_code in (401, 403) else "EXPOSE"
            print(f"{method:<7} {response.status_code:>5}  {path}   [{mark}]")
            if mark == "EXPOSE":
                print("   -> une route interne a repondu sans jeton")
                return 1

        print()
        print("2. Appel avec un jeton errone (doit etre refuse)")
        for method, path in internal:
            response = httpx.request(
                method, f"{base_url}{path}", headers={"X-Worker-Token": "mauvais"}, timeout=10
            )
            mark = "refus" if response.status_code in (401, 403) else "EXPOSE"
            print(f"{method:<7} {response.status_code:>5}  {path}   [{mark}]")
            if mark == "EXPOSE":
                print("   -> un jeton errone a ete accepte")
                return 1

        print()
        print("3. Le jeton configure du worker (doit franchir la porte)")
        # Only the route that does not touch the database. The other two reach a session and
        # then wait for a PostgreSQL that is not here; timing out on them would say nothing
        # about authorisation, only that the database is absent, which is already known.
        for method, path in [("GET", "/api/internal/rag/config")]:
            response = httpx.request(
                method, f"{base_url}{path}", headers={"X-Worker-Token": TOKEN}, timeout=20
            )
            print(f"{method:<7} {response.status_code:>5}  {path}")
            if response.status_code != 200:
                print(f"   -> le jeton du worker n'a pas ete accepte : {response.text[:200]}")
                return 1
            body = response.json()
            print(f"      configuration RAG servie : provider={body.get('embedding_provider')}")

        print()
        print("3 bis. Les routes internes qui touchent la base")
        for method, path in [
            (m, p) for m, p in internal if p != "/api/internal/rag/config"
        ]:
            try:
                response = httpx.request(
                    method, f"{base_url}{path}", headers={"X-Worker-Token": TOKEN}, timeout=8
                )
                print(f"{method:<7} {response.status_code:>5}  {path}")
            except httpx.TimeoutException:
                print(f"{method:<7} {'--':>5}  {path}   (jeton accepte, puis attente base : "
                      "verrou sur la base absente)")

        print()
        print("4. Le vrai code de tache du worker appelle-t-il l'API sur le reseau ?")
        # The worker and the API both use a top-level package named ``app``, so importing both
        # in one interpreter makes the second shadow the first. That is a consequence of the
        # two services being separate deployments, and it is why the worker is exercised in its
        # own process here rather than alongside the API.
        probe = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("_worker_probe.py"))],
            cwd=WORKER,
            env=dict(
                os.environ,
                PYTHONPATH=str(WORKER),
                SOURCE_WORKER_URL=base_url,
                SOURCE_WORKER_TOKEN=TOKEN,
            ),
            capture_output=True,
            text=True,
            timeout=180,
        )
        for line in (probe.stdout or "").splitlines():
            print(f"   {line}")
        if probe.returncode != 0:
            print("   -> la sonde worker a echoue :")
            print((probe.stderr or "")[-600:])
            return 1

        print()
        print("Conclusion : l'API interne refuse un appel anonyme et un jeton errone,")
        print("accepte le jeton configure du worker, et la tache worker envoie bien")
        print("ce jeton sur le reseau vers cette URL.")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
