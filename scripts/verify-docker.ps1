param(
  [string]$BaseUrl = "http://localhost:8000",
  [string]$FrontendUrl = "http://localhost:3000"
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
  throw "Docker CLI introuvable. Installez Docker Desktop puis relancez le script."
}

Write-Host "1/10 Vérification de l'API live..."
$live = Invoke-WebRequest -UseBasicParsing "$BaseUrl/health/live"
if ($live.StatusCode -ne 200) { throw "L'API live ne répond pas." }

Write-Host "2/10 Vérification de la readiness (PostgreSQL + Redis)..."
$ready = Invoke-WebRequest -UseBasicParsing "$BaseUrl/health/ready"
if ($ready.StatusCode -ne 200) { throw "Une dépendance de l'API n'est pas prête." }

Write-Host "3/10 Vérification du frontend..."
$frontend = Invoke-WebRequest -UseBasicParsing $FrontendUrl
if ($frontend.StatusCode -ne 200) { throw "Le frontend ne répond pas." }

Write-Host "4/10 Vérification du proxy de health frontend..."
$frontendHealth = Invoke-WebRequest -UseBasicParsing "$FrontendUrl/api/health"
if ($frontendHealth.StatusCode -ne 200) { throw "Le proxy frontend ne répond pas." }

Write-Host "5/10 Vérification de PostgreSQL..."
$postgres = docker compose exec -T postgres pg_isready -U academic_memo -d academic_memo
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL n'est pas prêt." }
Write-Output $postgres

Write-Host "6/10 Vérification de l'extension pgvector..."
$vector = docker compose exec -T postgres psql -U academic_memo -d academic_memo -tAc "SELECT extname FROM pg_extension WHERE extname = 'vector';"
$vectorText = ($vector -join "`n").Trim()
if ($LASTEXITCODE -ne 0 -or $vectorText -ne "vector") { throw "L'extension vector n'est pas installée." }
Write-Output $vector

Write-Host "7/10 Vérification de Redis..."
$redis = docker compose exec -T redis redis-cli ping
$redisText = ($redis -join "`n").Trim()
if ($LASTEXITCODE -ne 0 -or $redisText -ne "PONG") { throw "Redis ne répond pas." }
Write-Output $redis

Write-Host "8/10 Vérification des tables de sources..."
$sourceTable = docker compose exec -T postgres psql -U academic_memo -d academic_memo -tAc "SELECT to_regclass('public.source_processing_jobs');"
$sourceTableText = ($sourceTable -join "`n").Trim()
if ($LASTEXITCODE -ne 0 -or $sourceTableText -ne "source_processing_jobs") { throw "La migration des sources n'est pas appliquée." }

Write-Host "9/10 Vérification du worker Celery..."
$worker = docker compose exec -T worker celery -A app.worker.celery_app inspect ping --timeout=5
if ($LASTEXITCODE -ne 0) { throw "Le worker Celery ne répond pas." }
Write-Output $worker

Write-Host "10/10 Vérification des guards d'authentification..."
$csrf = Invoke-WebRequest -UseBasicParsing "$BaseUrl/api/auth/csrf"
if ($csrf.StatusCode -ne 200) { throw "Le endpoint CSRF ne répond pas." }
try {
  Invoke-WebRequest -UseBasicParsing "$BaseUrl/api/auth/me" | Out-Null
  throw "Une route privée a répondu sans session."
} catch {
  $statusCode = $_.Exception.Response.StatusCode.value__
  if ($statusCode -ne 401) { throw "La route privée n'a pas répondu 401." }
}

Write-Host "Toutes les vérifications Docker sont passées."
