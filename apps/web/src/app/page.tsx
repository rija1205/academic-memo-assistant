import Link from "next/link";
import { HealthStatus } from "@/components/health-status";

const publicApiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const services = [
  {
    title: "Frontend Next.js",
    description: "Interface React/TypeScript prête à accueillir les futures vues de l’application.",
    value: "apps/web",
  },
  {
    title: "API FastAPI",
    description: "API de fondation avec documentation OpenAPI et endpoints de santé.",
    value: "services/api",
  },
  {
    title: "Données et services",
    description: "PostgreSQL avec pgvector, Redis et worker Celery sont orchestrés par Docker.",
    value: "docker-compose.yml",
  },
];

export default function HomePage() {
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
          <div>
            Academic Memo Assistant
            <small>Authentification · étape 3</small>
          </div>
        </div>
        <span>ThesisFlow visual foundation</span>
      </header>

      <main className="container">
        <p className="eyebrow">Assistant de mémoire académique</p>
        <h1>Une base fiable pour une recherche traçable.</h1>
        <p className="lead">
          Le projet est prêt à évoluer vers l’importation de sources, l’assistant de rédaction,
          les citations vérifiables et l’analyse de cohérence. Cette première version reste
          volontairement limitée à l’infrastructure technique.
        </p>

        <div className="actions">
          <Link className="button button--primary" href="/login">
            Se connecter
          </Link>
          <Link className="button" href="/register">
            Créer un compte
          </Link>
          <a className="button" href={`${publicApiUrl}/docs`} target="_blank" rel="noreferrer">
            Documentation API
          </a>
        </div>

        <HealthStatus />

        <section className="grid" aria-label="Services de la fondation">
          {services.map((service) => (
            <article className="card" key={service.title}>
              <h2>{service.title}</h2>
              <p>{service.description}</p>
              <p><code>{service.value}</code></p>
            </article>
          ))}
        </section>

        <p className="footer">
          Les fonctionnalités métier, le RAG, OpenAI et les intégrations Google seront ajoutés
          dans les étapes suivantes, après validation de cette fondation.
        </p>
      </main>
    </div>
  );
}
