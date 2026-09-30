# Préparation de l’étape 6 — RAG

L’étape 5 fournit les données nécessaires au futur RAG sans calculer d’embedding :

- `sources` décrit le document et son projet ;
- `source_files` décrit l’objet stocké ;
- `source_pages` conserve le texte par page ;
- `source_blocks` conserve blocs, positions et `provenance_id` ;
- `source_processing_jobs` trace les traitements et les échecs.

Les champs `source_count` et `reference_count` du résumé projet sont maintenant calculés à partir des sources. Le compteur de références reste à zéro tant que la table des références académiques n’existe pas.

L’étape 6 pourra ajouter `pgvector`, les embeddings, la recherche hybride et la citation automatique en s’appuyant sur `provenance_id`. Aucun embedding ni RAG n’est créé à ce stade.
