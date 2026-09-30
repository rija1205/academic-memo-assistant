# Worker Celery

Worker de l'import et du traitement des sources académiques. L'API conserve la propriété des données et le worker appelle le pipeline interne protégé par `X-Worker-Token`.

## Exécution locale

Après avoir lancé Redis sur `localhost` et vérifié les variables `SOURCE_WORKER_URL` et `SOURCE_WORKER_TOKEN` :

```bash
celery -A app.worker.celery_app worker -Q sources,celery --loglevel=INFO
```

La tâche `system.ping` et la tâche `sources.process_source` sont enregistrées dans `app.worker.tasks`.
