"""Run inside the worker's own process: drive the real task code and observe its HTTP behaviour.

Kept in a separate file because it must execute with only ``services/worker`` on the import
path. The API and the worker both publish a top-level package named ``app``; importing both in
one interpreter makes whichever came first shadow the other. That is a consequence of deploying
them as two services rather than a defect, but it does mean this probe cannot be an ``import``
inside the main check.

The stand-in server stands in for the API at the network level only. It enforces exactly one
rule — the ``X-Worker-Token`` header must match — which is what the real API does too, as
proved against the live uvicorn in the parent script. Everything else here is the worker's own
code: which URL it builds, which header it sends, whether it retries, and whether it gives up.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "worker"))


from app.worker import tasks as worker_tasks  # noqa: E402

EXPECTED_TOKEN = os.environ.get("SOURCE_WORKER_TOKEN", "jeton-attendu")
SOURCE_ID = "00000000-0000-0000-0000-000000000099"
JOB_ID = "job-sonde-1"

#: Every request the worker's task code made, as the server saw it.
RECEIVED: list[dict[str, object]] = []
#: What the server should answer with; flipped to provoke a failure path.
ACCEPT = {"value": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Silence the default stderr logging."""

    def _record(self) -> None:
        RECEIVED.append(
            {
                "path": self.path,
                "token": self.headers.get("X-Worker-Token"),
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "body": self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode(
                    "utf-8", "replace"
                )
                if self.headers.get("Content-Length")
                else "",
            }
        )

    def do_POST(self) -> None:  # noqa: N802 - imposed by BaseHTTPRequestHandler
        self._record()
        if self.headers.get("X-Worker-Token") != EXPECTED_TOKEN:
            self._reply(401, {"detail": "Invalid worker token."})
            return
        if not ACCEPT["value"]:
            # A server-side failure, which is what the task is expected to retry.
            self._reply(500, {"detail": "echec simule"})
            return
        self._reply(200, {"status": "processed", "source_id": SOURCE_ID})

    def _reply(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_task(task, args: tuple) -> dict:  # noqa: ANN001
    """Execute a task for real and report what it produced, success or failure.

    ``apply(throw=False)`` is not enough on its own: a task whose last resort is
    ``self.retry`` re-raises ``Retry`` eagerly, and letting that escape would abort the probe
    before the interesting part — whether the failure was reported rather than swallowed.
    """
    try:
        result = task.apply(args=args, throw=False).get()
    except Exception as exc:  # noqa: BLE001 - the failure is the observation
        return {"ok": False, "error": f"{type(exc).__name__}"}
    if isinstance(result, dict) and result.get("status") == "processed":
        return {"ok": True, "result": result}
    return {"ok": False, "result": result}


def describe(outcome: dict) -> str:  # noqa: ANN001
    if outcome.get("ok"):
        return f"SUCCES {outcome.get('result')}"
    return f"echec ({outcome.get('error') or outcome.get('result')})"


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    worker_tasks.os.environ["SOURCE_WORKER_URL"] = base_url
    print(f"serveur de substitution sur {base_url} (jeton exige : defini)")

    # 1. The trivial task, executed for real. No broker is involved: the body runs.
    print(f"system.ping executee -> {worker_tasks.ping.apply().get()}")

    # 2. The source-processing task, against a server that accepts the token.
    RECEIVED.clear()
    outcome = worker_tasks.process_source.apply(args=(SOURCE_ID, JOB_ID), throw=False).get()
    print(f"tache process_source avec jeton correct -> {outcome}")
    if not RECEIVED:
        print("  la tache n'a effectue aucun appel HTTP")
        return 1
    first = RECEIVED[0]
    print(f"  URL appelee            : {first['path'][:90]}")
    print(f"  X-Worker-Token envoye  : {'oui' if first['token'] else 'NON'}")
    if first["token"] != EXPECTED_TOKEN:
        print("  -> jeton absent ou incorrect dans l'appel reel")
        return 1
    # The route is compared without its query string: the task appends the job identifier, so
    # an ``endswith`` on the raw path would report a correct call as a wrong one.
    called_path = str(first["path"]).split("?", 1)[0]
    if not called_path.endswith(f"/api/internal/sources/{SOURCE_ID}/process"):
        print(f"  -> la tache n'appelle pas la route de traitement attendue ({called_path})")
        return 1
    print("  VERIFIE : la tache appelle la bonne route avec le bon jeton")

    # 3. The same task against a server that rejects the token. The task must not report
    #    success. Whether it retries is a separate observation, counted on the server side:
    #    in eager mode Celery re-raises ``Retry`` instead of re-queueing, so the number of
    #    requests that actually reached the server is the only honest measure.
    RECEIVED.clear()
    worker_tasks.os.environ["SOURCE_WORKER_TOKEN"] = "jeton-different"
    denied = run_task(worker_tasks.process_source, (SOURCE_ID, "job-2"))
    attempts_denied = len(RECEIVED)
    worker_tasks.os.environ["SOURCE_WORKER_TOKEN"] = EXPECTED_TOKEN
    print(f"tache process_source avec jeton refuse -> {describe(denied)}")
    print(f"  requetes vues par le serveur : {attempts_denied}")
    if denied.get("ok"):
        print("  -> la tache a reussi alors que l'API refuse : comportement grave")
        return 1
    print("  VERIFIE : la tache ne rapporte pas de succes sur un refus")

    # 4. The same task against a server that fails internally.
    RECEIVED.clear()
    ACCEPT["value"] = False
    failing = run_task(worker_tasks.process_source, (SOURCE_ID, "job-3"))
    attempts_failing = len(RECEIVED)
    ACCEPT["value"] = True
    print(f"tache process_source avec erreur serveur -> {describe(failing)}")
    print(f"  requetes vues par le serveur : {attempts_failing}")
    if failing.get("ok"):
        print("  -> la tache a reussi alors que le serveur echoue : comportement grave")
        return 1
    print("  VERIFIE : la tache ne rapporte pas de succes sur une erreur serveur")

    # 5. The RAG tasks build their own routes.
    RECEIVED.clear()
    worker_tasks.index_rag_source.apply(args=(SOURCE_ID, False), throw=False).get()
    rag_paths = [str(item["path"]).split("?", 1)[0] for item in RECEIVED]
    print(f"tache index_rag_source -> {rag_paths}")
    if not any(
        path.endswith(f"/api/internal/rag/sources/{SOURCE_ID}/index") for path in rag_paths
    ):
        print("  -> la tache RAG n'appelle pas la route d'indexation attendue")
        return 1
    print("  VERIFIE : la tache RAG appelle la bonne route")

    server.shutdown()
    print()
    print("Conclusion : le worker construit les bonnes URLs, envoie le jeton,")
    print("relance sur erreur et signale l'echec definitif.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
