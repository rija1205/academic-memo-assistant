# ADR 0001 — Monolithe modulaire

## Statut

Accepté pour l'étape 2.

## Décision

Utiliser un frontend, une API et un worker séparés dans un monorepo, avec frontières de modules explicites. Ne pas créer de microservices indépendants au démarrage.

## Raisons

- réduction de la complexité de déploiement ;
- transactions et contrôles d'accès plus simples entre projets et documents ;
- possibilité d'extraire un module plus tard si la charge le justifie ;
- développement et tests locaux plus rapides.
