# Étape 5 — Importation et bibliothèque des sources

## Flux

```text
Upload
  ↓
Validation extension + MIME + signature + SHA-256
  ↓
Stockage provider
  ↓
source_files + source_processing_jobs
  ↓
Celery (file sources.process_source)
  ↓
API interne /internal/sources/{id}/process
  ↓
Extraction → OCR si nécessaire → nettoyage
  ↓
source_pages + source_blocks + provenance_id
  ↓
Source processed
```

Le mode `SOURCE_PROCESSING_MODE=sync` est réservé aux tests et au développement sans broker. En mode `async`, l'API ne bloque pas la requête et le worker traite le fichier.

## Stockage

`app/storage/base.py` définit `StorageProvider`. `LocalStorageProvider` écrit sous une racine isolée et refuse la traversée de chemin. `ObjectStorageProvider` utilise l'API S3 et peut cibler AWS S3, MinIO ou un autre service compatible. PostgreSQL ne contient que les métadonnées et la clé de stockage.

## Formats

- PDF : pages, texte, métadonnées natives ; OCR injectable si le PDF est scanné ;
- DOCX : paragraphes, titres, tableaux et propriétés ;
- TXT/Markdown : texte UTF-8 et blocs ;
- CSV/XLSX : lignes, colonnes et feuilles sans transformation silencieuse des valeurs ;
- PNG/JPEG : OCR injectable.

Une métadonnée absente reste `null` et est affichée « Non renseigné ». Le pipeline n'invente ni auteur, ni DOI, ni année.

## Provenance et recherche

Chaque `source_block` possède un `provenance_id`, une page, un index de bloc et ses positions dans la page. La recherche locale utilise ces blocs et renvoie document, page, extrait et provenance. Elle ne produit aucun embedding.

## Sécurité

- permissions `reader`, `editor` et `owner` sur chaque route ;
- CSRF sur les mutations ;
- téléchargement réservé à `editor` et `owner` ;
- suppression de fichier sécurisée et réservée au propriétaire ;
- endpoint worker protégé par `X-Worker-Token` ;
- validation de la taille, de l'extension, du MIME et du contenu réel.

## OCR

`OcrProvider` est une interface interchangeable. `NullOcrProvider` est le comportement par défaut ; un PDF scanné ou une image sans OCR est marqué en échec avec un message explicite, sans perte du fichier original. Un adaptateur Tesseract, cloud ou autre peut être ajouté sans modifier le pipeline.
