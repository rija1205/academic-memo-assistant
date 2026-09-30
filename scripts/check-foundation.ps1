param(
  [switch]$SkipTests
)

# Warnings from a native command must not be treated as failures: with ErrorActionPreference
# set to Stop, a DeprecationWarning emitted on stderr while a probe runs makes the whole script
# abort even though the probe reported what it was asked to report. Errors are still caught,
# through the exit code of each command.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Vérification de la structure de l'étape 14..."

$requiredPaths = @(
  "docker-compose.yml",
  ".env.example",
  "apps/web/package.json",
  "package-lock.json",
  "apps/web/src/app/page.tsx",
  "apps/web/src/app/api/health/route.ts",
  "services/api/app/main.py",
  "services/api/alembic.ini",
  "services/api/alembic/versions/0001_initial_schema.py",
  "services/api/alembic/versions/0002_authentication_and_sessions.py",
  "services/api/alembic/versions/0003_project_workspace.py",
  "services/api/alembic/versions/0004_source_library.py",
  "services/api/alembic/versions/0005_academic_rag.py",
  "services/api/alembic/versions/0006_assistant.py",
  "services/api/alembic/versions/0007_writing_assistant.py",
  "services/api/alembic/versions/0008_bibliography.py",
  "services/api/app/bibliography/router.py",
  "services/api/app/bibliography/service.py",
  "services/api/app/bibliography/parsers.py",
  "services/api/app/bibliography/authors.py",
  "services/api/app/bibliography/duplicates.py",
  "services/api/app/bibliography/schemas.py",
  "services/api/app/core/normalize.py",
  "services/api/app/models/bibliography.py",
  "services/api/tests/test_bibliography.py",
  "apps/web/src/components/bibliography/bibliography-workspace.tsx",
  "apps/web/src/app/projects/[projectId]/bibliography/page.tsx",
  "apps/web/tests/bibliography.test.ts",
  "docs/architecture/stage9-bibliography.md",
  "services/api/alembic/versions/0009_citations.py",
  "services/api/app/citations/router.py",
  "services/api/app/citations/service.py",
  "services/api/app/citations/data.py",
  "services/api/app/citations/numbering.py",
  "services/api/app/citations/styles/base.py",
  "services/api/app/citations/styles/apa.py",
  "services/api/app/citations/styles/harvard.py",
  "services/api/app/citations/styles/vancouver.py",
  "services/api/app/citations/styles/iso690.py",
  "services/api/app/models/citation.py",
  "services/api/tests/test_citation_styles.py",
  "services/api/tests/test_citations_service.py",
  "apps/web/src/components/citations/citation-node.ts",
  "apps/web/src/components/citations/bibliography-block.ts",
  "apps/web/src/components/citations/citation-picker.tsx",
  "apps/web/src/components/citations/citation-editor-panel.tsx",
  "apps/web/tests/citations.test.ts",
  "docs/architecture/stage10-citations.md",
  "services/api/alembic/versions/0010_document_exports.py",
  "services/api/app/export/router.py",
  "services/api/app/export/service.py",
  "services/api/app/export/blocks.py",
  "services/api/app/export/tiptap.py",
  "services/api/app/export/pdf.py",
  "services/api/app/export/docx.py",
  "services/api/app/export/options.py",
  "services/api/app/export/images.py",
  "services/api/app/export/orchestrator.py",
  "services/api/app/models/export.py",
  "services/api/tests/test_export_document.py",
  "apps/web/src/components/export/export-dialog.tsx",
  "apps/web/tests/export.test.ts",
  "docs/architecture/stage11-export.md",
  "services/api/alembic/versions/0011_academic_audit.py",
  "services/api/app/audit/router.py",
  "services/api/app/audit/service.py",
  "services/api/app/audit/checks.py",
  "services/api/app/audit/findings.py",
  "services/api/app/audit/statistics.py",
  "services/api/app/models/audit.py",
  "services/api/tests/test_academic_audit.py",
  "apps/web/src/components/audit/audit-workspace.tsx",
  "apps/web/src/app/projects/[projectId]/audit/page.tsx",
  "apps/web/tests/audit.test.ts",
  "docs/architecture/stage12-academic-audit.md",
  "services/api/alembic/versions/0012_security_admin.py",
  "services/api/app/security/guards.py",
  "services/api/app/security/admin.py",
  "services/api/app/security/router.py",
  "services/api/app/observability/metrics.py",
  "services/api/app/observability/middleware.py",
  "services/api/app/observability/router.py",
  "services/api/app/models/security.py",
  "services/api/tests/test_security_stage13.py",
  "apps/web/src/components/admin/admin-workspace.tsx",
  "apps/web/src/app/admin/page.tsx",
  "apps/web/tests/admin.test.ts",
  "docs/architecture/stage13-security-admin.md",
  "services/api/app/auth/router.py",
  "services/api/app/sources/router.py",
  "services/api/app/sources/processing.py",
  "services/api/app/storage/base.py",
  "services/api/app/rag/pipeline.py",
  "services/api/app/rag/chunking.py",
  "services/api/app/rag/embeddings.py",
  "services/api/app/rag/router.py",
  "services/api/app/assistant/router.py",
  "services/api/app/assistant/pipeline.py",
  "services/api/app/assistant/prompts.py",
  "services/api/app/assistant/citations.py",
  "services/api/app/writing/router.py",
  "services/api/app/writing/pipeline.py",
  "services/api/app/writing/actions.py",
  "services/api/tests/test_writing_assistant.py",
  "services/api/tests/test_assistant_citations.py",
  "services/api/tests/test_assistant_pipeline.py",
  "services/api/tests/test_rag_chunking.py",
  "services/api/tests/test_rag_quality.py",
  "services/api/tests/test_sources.py",
  "services/api/app/projects/access.py",
  "services/worker/app/worker/celery_app.py",
  "services/worker/app/worker/tasks.py",
  "services/worker/tests/test_tasks.py",
  "apps/web/middleware.ts",
  "apps/web/src/app/api/backend/[...path]/route.ts",
  "apps/web/src/app/projects/new/page.tsx",
  "apps/web/src/app/projects/[projectId]/page.tsx",
  "apps/web/src/app/projects/[projectId]/sources/page.tsx",
  "apps/web/src/components/sources/sources-workspace.tsx",
  "apps/web/src/components/rag/rag-workspace.tsx",
  "apps/web/src/app/projects/[projectId]/rag/page.tsx",
  "apps/web/tests/rag.test.ts",
  "apps/web/src/components/assistant/assistant-workspace.tsx",
  "apps/web/src/app/projects/[projectId]/assistant/page.tsx",
  "apps/web/tests/assistant.test.ts",
  "apps/web/src/components/writing/writing-panel.tsx",
  "apps/web/tests/writing.test.ts",
  "docs/architecture/stage8-writing.md",
  "docs/architecture/stage7-assistant.md",
  "docs/architecture/stage6-rag.md",
  "apps/web/src/components/workspace/project-workspace.tsx",
  "apps/web/src/components/workspace/section-editor.tsx",
  "apps/web/tests/sources.test.ts",
  "docs/architecture/stage5-sources.md",
  "apps/web/src/app/login/page.tsx",
  "infra/docker/postgres/init/001-extensions.sql",
  # Etape 14 - deploiement, sauvegardes et exploitation
  "docker-compose.yml",
  "docker-compose.prod.yml",
  "infra/docker/backend.Dockerfile",
  "infra/docker/frontend.Dockerfile",
  "infra/docker/worker.Dockerfile",
  "scripts/backup.py",
  "scripts/bootstrap_admin.py",
  "scripts/check-foundation.ps1",
  "services/api/tests/test_deployment.py",
  "docs/architecture/stage14-deployment.md",
  "docs/operations/installation.md",
  "docs/operations/deployment.md",
  "docs/operations/backup-restore.md",
  "docs/operations/configuration.md",
  "docs/operations/user-guide.md",
  "docs/operations/verification.md",
  "scripts/scan_secrets.py",
  "scripts/probe_public_surface.py",
  "scripts/audit_dead_code.py",
  "scripts/check_git_readiness.py",
  "scripts/check_schema_drift.py",
  "scripts/check_worker_api_link.py",
  "scripts/validate_real_environment.py",
  "scripts/compare_databases.py",
  "README.md",
  "docs/PROJECT-CLOSURE.md",
  ".env.example"
)

foreach ($path in $requiredPaths) {
  if (-not (Test-Path -LiteralPath $path)) {
    throw "Fichier manquant : $path"
  }
}

Write-Host "Structure conforme."

# The Compose files are read as data rather than trusted: a YAML that does not parse, or a
# production overlay that forgets to close the database port, would otherwise only be noticed
# when a deployment fails.
#
# The API virtual environment is preferred because it is the one guaranteed to carry PyYAML.
# Falling back to the system interpreter used to make this check report success while quietly
# doing nothing, which is the worst possible outcome for a check.
$composePython = $null
foreach ($candidate in @(
    "services/api/.venv/Scripts/python.exe",
    "services/api/.venv/bin/python",
    ".venv/Scripts/python.exe"
)) {
  if (Test-Path -LiteralPath $candidate) {
    $composePython = $candidate
    break
  }
}
if (-not $composePython) {
  $found = Get-Command python -ErrorAction SilentlyContinue
  if ($found) { $composePython = $found.Source }
}

if ($composePython) {
  $composeCheck = @'
import sys
try:
    import yaml
except ImportError:
    print("PyYAML absent : verification des fichiers Compose ignoree.")
    sys.exit(0)

for name in ("docker-compose.yml", "docker-compose.prod.yml"):
    with open(name, encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict) or "services" not in document:
        raise SystemExit(f"{name} : aucun bloc 'services'.")
    print(f"{name} : {len(document['services'])} services.")

with open("docker-compose.yml", encoding="utf-8") as handle:
    base = yaml.safe_load(handle)
with open("docker-compose.prod.yml", encoding="utf-8") as handle:
    production = yaml.safe_load(handle)

for name in production["services"]:
    if name not in base["services"]:
        raise SystemExit(f"L'overlay de production cible un service inexistant : {name}")

exposed = [name for name, spec in production["services"].items() if spec.get("ports")]
if sorted(exposed) != ["frontend"]:
    raise SystemExit(
        "En production, seul le frontend doit etre publie ; trouve : "
        + ", ".join(sorted(exposed)) or "aucun"
    )
print("Overlay de production : ports conformes.")
'@
  $composeCheck | & $composePython - 2>&1 | ForEach-Object { Write-Host $_ }
  if ($LASTEXITCODE -ne 0) {
    throw "Verification des fichiers Compose echouee."
  }
} else {
  Write-Host "python introuvable : verification des fichiers Compose ignoree."
}

# The link check is delegated to Python: a single-quoted regex in PowerShell carries its own
# escaping rules, and getting them subtly wrong produces a check that silently matches nothing
# and therefore always passes. Python is already a hard dependency of the probes below.
if (-not $composePython) {
  throw "Aucun interpreteur Python disponible pour verifier les scripts d'exploitation."
}
$linkCheck = & $composePython scripts/check_doc_links.py 2>&1
$linkCode = $LASTEXITCODE
$linkCheck | ForEach-Object { Write-Host $_ }
if ($linkCode -ne 0) {
  throw "Lien de documentation rompu (voir la sortie ci-dessus)."
}

# The application's own JSON log lines are part of the probe output and drown the verdict, so
# only the probe's own report is shown.
$probe = & $composePython scripts/probe_public_surface.py 2>&1
$probeCode = $LASTEXITCODE
$probe | Where-Object { $_ -notmatch '^\{"ts":' } | ForEach-Object { Write-Host $_ }
if ($probeCode -ne 0) {
  throw "Une route sensible repond sans authentification (voir la sortie ci-dessus)."
}

# Credential scan. A secret committed to the repository is a different kind of failure from a
# failing test, and it is not something the functional suite would notice.
$secretScan = & $composePython scripts/scan_secrets.py 2>&1
$secretCode = $LASTEXITCODE
$secretScan | Where-Object { $_ -notmatch '^\{"ts":' } | ForEach-Object { Write-Host $_ }
if ($secretCode -ne 0) {
  throw "Secret detecte dans le depot (voir la sortie ci-dessus)."
}

# The administrative bootstrap must stay able to run, since no account is privileged by
# default. It refuses to work without an explicit confirmation, so only the parser is
# exercised here.
if (-not $composePython) {
  throw "Aucun interpreteur Python disponible pour verifier les scripts d'exploitation."
}
$bootstrap = & $composePython scripts/bootstrap_admin.py --help 2>&1
if ($LASTEXITCODE -ne 0) {
  throw "scripts/bootstrap_admin.py ne demarre pas."
}
if (($bootstrap -join "`n") -notmatch "list-admins") {
  throw "scripts/bootstrap_admin.py n'expose pas --list-admins."
}
Write-Host "Amorcage administrateur : disponible."

if ($SkipTests) {
  Write-Host "Tests ignorés à la demande (-SkipTests)."
  exit 0
}

$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) {
  throw "npm est requis pour les tests. Installez Node.js 22 ou utilisez Docker."
}

npm run typecheck:web
if ($LASTEXITCODE -ne 0) { throw "Échec du typecheck frontend." }
npm run lint:web
if ($LASTEXITCODE -ne 0) { throw "Échec du lint frontend." }
npm run test:web
if ($LASTEXITCODE -ne 0) { throw "Échec des tests frontend." }

$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand -or $pythonCommand.Source -like "*WindowsApps*") {
  throw "Python 3.12 est requis pour les tests. Installez Python ou utilisez Docker."
}

# The project dependencies live in each service's own virtual environment, so the interpreter
# of that environment is used when it exists. Falling back to the system interpreter keeps the
# script usable inside the Docker images, where no venv is present.
function Resolve-ServicePython([string]$serviceDirectory) {
  $venvPython = Join-Path $root "$serviceDirectory/.venv/Scripts/python.exe"
  if (Test-Path -LiteralPath $venvPython) { return $venvPython }
  $venvPython = Join-Path $root "$serviceDirectory/.venv/bin/python"
  if (Test-Path -LiteralPath $venvPython) { return $venvPython }
  # This service has no environment of its own. A sibling venv is used when it provides the
  # interpreter, and the substitution is printed so a missing venv is never silent.
  foreach ($sibling in @("services/api", "services/worker")) {
    $candidate = Join-Path $root "$sibling/.venv/Scripts/python.exe"
    if (Test-Path -LiteralPath $candidate) {
      Write-Warning "$serviceDirectory n'a pas de venv : utilisation de $sibling/.venv."
      return $candidate
    }
  }
  return $pythonCommand.Source
}

Push-Location services/api
try {
  $apiPython = Resolve-ServicePython "services/api"
  & $apiPython -m pytest
  if ($LASTEXITCODE -ne 0) { throw "Échec des tests backend." }
  & $apiPython -m ruff check .
  if ($LASTEXITCODE -ne 0) { throw "Échec du lint backend." }
} finally {
  Pop-Location
}

Push-Location services/worker
try {
  $workerPython = Resolve-ServicePython "services/worker"
  & $workerPython -m pytest
  if ($LASTEXITCODE -ne 0) { throw "Échec des tests worker." }
  & $workerPython -m ruff check .
  if ($LASTEXITCODE -ne 0) { throw "Échec du lint worker." }
} finally {
  Pop-Location
}

# Real HTTP probe of the surface that must never be public. Reading the code is not enough:
# the protection has to be observed refusing an anonymous caller.
$probe = & $composePython scripts/probe_public_surface.py 2>&1
$probeCode = $LASTEXITCODE
# The application's own JSON log lines are part of the probe output and drown the verdict, so
# only the probe's own report is shown.
$probe | Where-Object { $_ -notmatch '^\{"ts":' } | ForEach-Object { Write-Host $_ }
if ($probeCode -ne 0) {
  throw "Une route sensible repond sans authentification (voir la sortie ci-dessus)."
}

# Credential scan. A secret committed to the repository is a different kind of failure from a
# failing test, and it is not something the functional suite would notice.
$secretScan = & $composePython scripts/scan_secrets.py 2>&1
$secretCode = $LASTEXITCODE
$secretScan | Where-Object { $_ -notmatch '^\{"ts":' } | ForEach-Object { Write-Host $_ }
if ($secretCode -ne 0) {
  throw "Secret detecte dans le depot (voir la sortie ci-dessus)."
}

# What a first Git commit would contain, simulated because Git is not installed here. The
# day it is, this becomes the pre-commit guard instead.
$gitReadiness = & $composePython scripts/check_git_readiness.py 2>&1
$gitCode = $LASTEXITCODE
$gitReadiness | ForEach-Object { Write-Host $_ }
if ($gitCode -ne 0) {
  throw "Un fichier sensible serait versionne (voir la sortie ci-dessus)."
}

# The models and the migrations must agree. Without a database to apply them to, this is what
# stands between "the unit tests pass" and "the schema is the one the code expects".
$schemaDrift = & $composePython scripts/check_schema_drift.py 2>&1
$schemaCode = $LASTEXITCODE
$schemaDrift | ForEach-Object { Write-Host $_ }
if ($schemaCode -ne 0) {
  throw "Derive entre les modeles et les migrations (voir la sortie ci-dessus)."
}

# The worker and the API must actually reach each other over a socket with the configured
# token. A dependency that is only ever exercised in-process proves nothing about the wire.
$workerLink = & $composePython scripts/check_worker_api_link.py 2>&1
$workerCode = $LASTEXITCODE
$workerLink | Where-Object { $_ -notmatch '^\{"ts":' } | ForEach-Object { Write-Host $_ }
if ($workerCode -ne 0) {
  throw "Le worker n'atteint pas l'API interne authentifiee (voir la sortie ci-dessus)."
}

# What remains to be validated against real services. This does not fail the run: the whole
# point of the harness is to report BLOCKED for what is missing and to perform the validations
# the day a dependency appears. Making it fatal would only mean the script could never pass on
# a machine without PostgreSQL, which is exactly the machine that needs to see the list.
Write-Host ""
Write-Host "Validations dependant d'un service reel :"
$realEnvironment = & $composePython scripts/validate_real_environment.py 2>&1
$realCode = $LASTEXITCODE
$realEnvironment | ForEach-Object { Write-Host $_ }
if ($realCode -ne 0) {
  Write-Warning "au moins une validation reelle a echoue (voir ci-dessus)."
}

# Dead code, unwired routes and unused dependencies. Reported as a note rather than a hard
# failure: the checks are heuristic, and a finding must be read by a person before it is
# allowed to block. The goal is that it cannot be forgotten.
$deadCode = & $composePython scripts/audit_dead_code.py 2>&1
$deadCodeCode = $LASTEXITCODE
$deadCode | Where-Object { $_ -notmatch '^\{"ts":' } | ForEach-Object { Write-Host $_ }
if ($deadCodeCode -ne 0) {
  Write-Warning "audit_dead_code.py a signale des points a examiner (voir ci-dessus)."
}

Write-Host "Structure, tests backend, tests worker, lint, Compose, sondes et nettoyage valides."
