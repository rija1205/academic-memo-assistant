# Étape 6 — RAG académique avec pgvector

## Positionnement

Cette étape construit le **moteur de récupération** complet. Elle ne produit aucun texte :
elle retrouve des passages réellement présents dans les sources de l'utilisateur et renvoie
leur provenance exacte. La génération de réponses (chat, rédaction, citations automatiques)
reste hors périmètre et sera traitée séparément.

```text
Sources utilisateur
        ↓
Extraction (étape 5)
        ↓
source_blocks
        ↓
Chunking académique      app/rag/chunking.py
        ↓
Embeddings par lot         app/rag/embeddings.py
        ↓
pgvector                   rag_chunks.embedding
        ↓
Recherche vectorielle      app/rag/search/retrieval.py
        +
Recherche lexicale         ts_rank_cd + pg_trgm
        ↓
Fusion                     RRF (par défaut) ou normalisation
        ↓
Reranking (optionnel)      couverture de termes
        ↓
Passages + provenance      app/rag/provenance.py
```

## Configuration unique

La dimension des embeddings est définie **une seule fois** dans `Settings.embedding_dimension`
(`EMBEDDING_DIMENSION`). Elle est consommée par :

* le modèle SQLAlchemy `rag_chunks.embedding` (`Vector(EMBEDDING_DIMENSION)`) ;
* la migration `0005_academic_rag` ;
* le contrôle de dimension du fournisseur d'embeddings.

Changer la variable change le schéma, les modèles et la couche de recherche de façon
cohérente. Un modèle qui renvoie une dimension différente lève une erreur explicite
(`EmbeddingDimensionMismatch`) au lieu d'échouer plus tard dans PostgreSQL.

## Chunking académique

`app/rag/chunking.py` respecte :

* **les phrases** : le découpage se fait sur les boundaries de phrases, avec protection des
  abréviations (`fig.`, `p.`, `etc.`) et des nombres décimaux (`3.14`) ;
* **les paragraphes** : les blocs contigus d'une même page sont regroupés ;
* **les titres** : un titre ferme le passage en cours et devient le contexte du suivant. Le
  chemin de titres est conservé dans les métadonnées et, si activé, préfixé au texte ;
* **les pages** : un chunk ne traverse jamais deux pages, donc la provenance de page est
  exacte ;
* **l'ordre** : `chunk_index` croît strictement sur l'ensemble du document.

Paramètres configurables : `CHUNK_MAX_TOKENS` (900), `CHUNK_OVERLAP_TOKENS` (120),
`CHUNK_MIN_TOKENS` (40). L'overlap porte sur des phrases complètes. Un chunk final trop petit
est **signalé** par `undersized: true` plutôt que fusionné : fusionner déborderait la taille
maximale ou effacerait une frontière de titre, ce qui corromprait le contexte.

## Embeddings

* `MockEmbeddingProvider` : déterministe, hors ligne, sans réseau. Il produit un vrai vecteur
  sac-de-mots normalisé : deux passages qui partagent du vocabulaire obtiennent un score de
  similarité élevé, deux passages sans rapport obtiennent un score proche de zéro. C'est ce
  qui rend Recall@K et MRR mesurables sans dépendance externe.
* `OpenAIEmbeddingProvider` : appels HTTP par lot vers l'API d'embeddings, avec retries et
  validation de dimension.

La clé d'API est lue uniquement côté serveur (`EMBEDDING_API_KEY`). Aucun schéma public ne
l'expose ; `tests/test_rag_config.py` le vérifie explicitement.

## Indexation

`app/rag/pipeline.py` exécute `source_blocks → chunks → embeddings → pgvector` avec les états
`pending`, `chunking`, `embedding`, `indexed`, `failed`.

**Idempotence.** Chaque index porte une signature (`RagTuning.index_signature`) construite
depuis le fournisseur, le modèle, la dimension, la version d'embedding et les paramètres de
chunking. Si la signature est inchangée et le statut `indexed`, l'index est réutilisé. Un
changement de modèle ou de chunking produit une signature différente : le document est marqué
`needs_reindex` et l'interface propose « Réindexer ».

**Concurrence.** La ligne `RagDocument` est verrouillée par `SELECT ... FOR UPDATE` et les
anciens chunks sont remplacés dans une seule transaction.

**Asynchronie.** En mode `async`, l'API publie une tâche Celery `rag.index_source` et n'attend
rien. En mode `sync`, l'indexation est inline (utilisé par les tests). L'indexation automatique
est déclenchée par `app/rag/autoindex.py` dès qu'une source atteint le statut `processed` :
l'utilisateur n'a rien à lancer.

## Recherche

* **Vectorielle** : `1 - (embedding <=> query)` via l'index HNSW `vector_cosine_ops`.
* **Lexicale** : `ts_rank_cd` sur un `tsvector` (config `simple`, disponible partout) combiné
  à `similarity()` de `pg_trgm` pour les termes partiels ou mal orthographiés. Fonctionne
  sans aucun embedding.
* **Hybride** : fusion explicite, jamais une concaténation.

### Fusion RRF

Reciprocal Rank Fusion compare les **positions**, pas les scores bruts, ce qui est nécessaire
quand une distance cosinus et un `ts_rank` vivent sur des échelles différentes :

```text
score(chunk) = Σ  poids / (k + rang)      k = RAG_RRF_K (60)
```

Une alternative par normalisation min-max est disponible via `RAG_FUSION_METHOD=normalized`.

### Reranking

Optionnel. `RERANKER_PROVIDER=none` (défaut) laisse l'ordre de fusion intact. Le reranker
`mock` disponible ici est déterministe et explicable : couverture des termes de la question
pondérée à 25 %, score de récupération conservé à 75 %, pour qu'aucun passage pertinent ne
soit jamais entièrement écarté. L'interface `RerankerProvider` permet d'ajouter un reranker
externe sans toucher à la couche de fusion.

## Filtres

Source, type de publication, année (bornes), auteur, page (bornes), dossier, tags. Toutes les
conditions sont combinées avec `rag_chunks.project_id`, qui est toujours la première condition
de la requête.

## Provenance

Chaque résultat expose la chaîne complète :

```text
projet → source → fichier → page → bloc → provenance_id → chunk
```

Objet `RagProvenance` : `project_id`, `source_id`, `source_file_id`, `page_number`,
`block_start`, `block_end`, `chunk_id`, `provenance_id`, positions caractère, chemin de
titres, et `source_url` pointant vers la page exacte de la source.

## Suppression

* Suppression d'une source : les chunks sont supprimés immédiatement, la source reste en
  soft-delete comme prévu par la politique existante.
* Désindexation : retire les chunks de la recherche, conserve la ligne `RagDocument` en
  tombstoue (`deleted_at`), sans supprimer la source.

## Sécurité et permissions

| Rôle | Recherche | Indexation | Réindexation | Désindexation |
|------|-----------|------------|--------------|---------------|
| owner  | oui | oui | oui | oui |
| editor | oui | oui | oui | oui |
| reader | oui | non (403) | non (403) | non (403) |

L'isolation est appliquée dans la couche SQL, pas seulement dans le routeur : la condition de
projet est construite par `build_filter_conditions` et precede tout autre critère.

## Coûts

`app/rag/cost.py` suit le nombre de documents, de chunks et de tokens envoyés, et estime le
coût si un tarif est connu (tarif de référence ou
`EMBEDDING_PRICE_PER_MILLION_TOKENS_USD`). Si le tarif est inconnu, le rapport indique
« non disponible » au lieu d'inventer un montant, et l'application n'est jamais bloquée.

## Exécution de l'étape 6

```text
Je téléverse mes articles
        ↓
Les documents sont traités et indexés automatiquement
        ↓
Je pose une question
        ↓
Le système retrouve les passages pertinents
        ↓
Je vois la source, la page et la provenance
```

Aucune génération de réponse par un modèle de langage n'intervient à ce stade.
