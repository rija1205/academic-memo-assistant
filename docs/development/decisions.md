# Checklist de validation — étape 5

- [ ] `docker compose config` valide le pipeline de sources.
- [ ] `alembic upgrade head` crée les sept tables de la bibliothèque.
- [ ] un utilisateur importe un PDF, DOCX, TXT, Markdown, CSV, XLSX ou image.
- [ ] une extension dangereuse, un MIME falsifié et un fichier corrompu sont refusés.
- [ ] la taille maximale est appliquée avant le stockage.
- [ ] un doublon SHA-256 demande une confirmation et n'est jamais supprimé automatiquement.
- [ ] le fichier original est conservé quand l'extraction échoue.
- [ ] le statut passe par `uploaded`, `processing`, `processed` ou `failed`.
- [ ] l'aperçu affiche les pages, blocs et `provenance_id`.
- [ ] la recherche locale renvoie document, page, extrait et provenance.
- [ ] un lecteur ne peut pas télécharger, importer ou supprimer une source.
- [ ] un éditeur peut importer, modifier, télécharger et rechercher.
- [ ] un propriétaire peut supprimer et gérer les dossiers.
- [ ] un utilisateur non membre ne peut pas modifier un identifiant de source.
- [ ] le worker Celery traite la file `sources` et signale les échecs.
- [ ] les tests frontend, backend et d'intégration passent.

L'étape 6 ne doit pas commencer avant la validation de cette checklist.
