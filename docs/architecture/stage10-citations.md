# Étape 10 — Citations académiques et bibliographie automatique

## Principe directeur

**Une citation ne stocke jamais le texte affiché comme source de vérité.** Elle stocke
l'identité des références qu'elle pointe, et le texte est produit à la demande par le moteur
de style à partir des métadonnées vivantes de ces références.

```text
ReferenceCitationData  (ce que sait la référence, lu en base)
        ↓
CitationData           (identité : citationId + referenceIds)
        ↓
CitationStyle.format_citation()      → "(Dupont, 2024, p. 25)"
CitationStyle.format_bibliography_entry() → "Dupont, J. (2024). Titre…"
```

Trois exigences du cahier des charges découlent de ce choix unique, sans travail
supplémentaire :

* **synchronisation** (§22) : corriger l'année d'une référence met à jour toutes ses citations
  **sans aucune écriture**, donc sans risque de dérive ;
* **changement de style** : aucune migration, le texte est recalculé ;
* **style numérique** : la numérotation est recalculée, pas stockée.

Le seul texte figé est `snapshot_text`, capté à l'écriture de la citation, et il sert
uniquement à garder une ancienne révision ou une référence supprimée lisible.

## Modèle de données

Migration `0009_citations` (`down_revision = 0008_bibliography`).

### `citations`

| colonne | rôle |
|---|---|
| `project_id`, `section_id` | appartenance ; `section_id` en `CASCADE` |
| `node_id` | jeton stable du nœud Tiptap, `UNIQUE` |
| `position_in_section` | ordre dans la section, pour Vancouver |
| `citation_key` | clé interne lisible, jamais une donnée bibliographique |
| `prefix`, `suffix`, `locator_type`, `locator_value`, `mode` |_affixes_ et mode |
| `snapshot_style`, `snapshot_text`, `snapshot_data` | historique, **pas** la vérité |
| `is_orphaned` | indice mis en cache ; la vérité est recalculée en lecture |

### `citation_items`

`citation_id`, `reference_id`, `position`, `locator_type`, `locator_value`, `prefix`,
`suffix`, avec `UNIQUE(citation_id, position)`.

Aucune métadonnée bibliographique n'est dupliquée : `reference_id` est un `FOREIGN KEY`
vers `bibliographic_references`.

### `reference_authors.is_organization`

Ajoutée en `0009` avec `DEFAULT false`, donc additive : les auteurs créés à l'étape 9 restent
des personnes. Elle permet d'écrire `FAO (2023)` sans deviner, et un patron capitalized comme
`DUPONT` reste une personne — le drapeau est explicite, jamais inféré.

### Stratégie de conservation

* Supprimer une **section** supprime ses citations, comme ses révisions déjà.
* Supprimer une **citation** ne supprime jamais la référence.
* Supprimer une **référence** (soft delete étape 9) la rend orpheline : la citation affiche
  « Citation invalide : référence introuvable » et le `snapshot_text` est renvoyé à côté pour
  que l'historique reste explicable.

## Extension Tiptap

Deux nœuds, tous deux des atomes que l'auteur ne peut pas éditer comme du texte.

### `citation`

```json
{
  "type": "citation",
  "attrs": {
    "citationId": "cit-abc123",
    "referenceIds": ["…", "…"],
    "mode": "parenthetical",
    "locatorType": "page",
    "locatorValue": "25",
    "prefix": "Voir ",
    "suffix": ", p. 25",
    "text": "(Voir Dupont, 2024, p. 25)",
    "isOrphaned": false,
    "warnings": []
  }
}
```

`text` n'est là que pour l'affichage ; il est réécrit à chaque sauvegarde. Le HTML conserve
`data-citation-id` et `data-reference-ids`, ce qui permettra aux exports PDF/DOCX de
re-rendre la citation sans refaire la logique.

**Compatibilité étape 3** : le placeholder `citation` de l'étape 3 ne portait qu'une clé libre
(`{ "value": "Auteur2025" }`). Il est conservé en lecture via `legacyValue`, rendu lisible, et
signalé comme `unregistered_node_ids` — jamais converti en citation, car une clé libre n'est
pas un identifiant de référence.

### `bibliographyBlock`

Atomique, non déplaçable, avec `blockId`, `lines`, `entryCount`, `uncitedCount`,
`orphanCount`, `isStale`. L'auteur ne saisit rien dedans.

## Moteur de style

Abstraction unique dans `app/citations/styles/base.py` :

```python
format_citation(citation) -> RenderedCitation
format_bibliography_entry(reference, number=, year_suffix=) -> RenderedBibliographyEntry
sort_bibliography(references) -> list[ReferenceCitationData]
assign_year_suffixes(references) -> dict[reference_id, "a"|"b"|…]
```

`app/citations/styles/__init__.py` expose `STYLE_REGISTRY`, `get_style`, `available_styles`.
**Aucun composant React ni endpoint ne teste `style == "apa"`** : l'aperçu passe par
`POST /citations/preview`, qui appelle le même moteur que le rendu final.

Les entrées du moteur (`app/citations/data.py`) sont des dataclasses sans dépendance à
SQLAlchemy : le rendu est donc testable sans base et réutilisable tel quel pour Tiptap HTML,
PDF, DOCX et texte brut (§31).

### Styles implémentés

| style | in-text | référence |
|---|---|---|
| **APA 7** | `(Dupont, 2024)`, `(Dupont & Martin, 2024)`, `(Dupont et al., 2024)` | `Dupont, J., & Martin, P. (2024).` |
| **Harvard** | `(Dupont, 2024)`, `(Dupont and Martin, 2024)` | `Dupont, J. and Martin, P. (2024).` |
| **Vancouver** | `[1]`, `[1-3]`, `[1,3,5]` | `1. Dupont. Titre. 2024.` |
| **ISO 690** | `[1]` | `1. Dupont, J. Titre. Éditeur, 2024. p. 25-40.` |

**APA 7** — 1 auteur `Dupont` ; 2 `Dupont & Martin` ; 3+ `Dupont et al.` ; liste de références :
tous les auteurs jusqu'à 20, puis les 19 premiers + `. . . ` + le dernier seul. Virgule
sériale à 2 auteurs. Thèse entre crochets. `s.d.` si pas d'année.

**Harvard** — `and` au lieu de `&`, `n.d.` si pas d'année. 1, 2 et 3 auteurs nommés
(convention *Cite Them Right*), 4+ `et al.`.

**Vancouver** — le numéro est **l'ordre de première citation dans le document**, calculé par
`app/citations/numbering.py`, qui est un ordre total et déterministe : `A→[1], B→[2], A→[1],
C→[3]`, et après suppression de `B`, `A→[1], C→[2]`. Les numéros consécutifs sont fusionnés.

**ISO 690** — **variante documentée : forme numérique ISO 690:2010 en anglais.** Les variantes
nationales (NF Z 74-002 française, GOST) ne sont **pas** implémentées et le libellé de
l'interface le dit : « ISO 690 (numérique) ». Ordre des éléments : responsabilité, titre,
édition, lieu, éditeur, date, étendue, DOI.

### Style du projet

`projects.bibliography_style` (existant depuis `0003`, défaut `apa`) est lu par
`resolve_project_style`. Les alias et valeurs historiques (`apa`, `APA7`, `ICMJE`, `iso-690`…)
sont résolus sans jamais réécrire le choix de l'utilisateur. `?style=` permet un aperçu sans
modifier le projet.

## Locators, préfixe, suffixe

`locator_type ∈ {page, pages, chapter, figure, table, section, other}` avec libellé par style
(`p.`, `pp.`, `chap.`, `fig.`, `tableau`…). **Un locator sans valeur n'ajoute rien** : aucune
page n'est déduite du seul type. La plage est saisie par l'auteur et reproduite telle quelle,
jamais reconstruite.

Préfixe et suffixe sont utilisés **verbatim** ; un espace n'est ajouté que si l'affixe ne
fournit pas déjà son séparateur, pour que `prefix="Voir "` et `suffix=", p. 25"` produisent
`(Voir Dupont, 2024, p. 25)` sans espace parasite.

## Citations narratives

`mode ∈ {parenthetical, narrative}`. En mode narratif, le premier auteur sort des
parenthèses : `Dupont (2024)`. Les références multiples restent groupées.

## Bibliographie automatique

`GET /bibliography/rendered` et `POST /bibliography/refresh` produisent la bibliographie
**depuis les références effectivement citées** :

* une référence citée plusieurs fois apparaît **une seule fois** ;
* une référence présente dans la bibliothèque mais jamais citée est renvoyée dans `uncited`,
  hors de la bibliographie — une référence dans la bibliothèque n'est pas une référence dans la
  bibliographie finale ;
* une citation orpheline est renvoyée dans `orphaned_citations` avec son `snapshot_text` ;
* `incomplete_count` compte les entrées qui signalent une information manquante.

Le bloc de l'éditeur est un **placeholder** : le texte est régénéré, le raisonnement de
l'auteur n'est jamais touché.

## Référencement

`reference_authors` conserve l'ordre de l'étape 9 ; le moteur ne le réordonne jamais.

Auteur institutionnel : drapeau explicite, rendu sans initiales. Une personne sans prénom
(`Aristote`) n'en reçoit pas.

## Synchronisation

Produite par construction. `reference` modifiée → le rendu suivant la lit. Le tableau
`citations` n'a aucune colonne de texte courant, donc il ne peut pas être désynchronisé. Le
champ `is_stale_snapshot` signale un snapshot qui ne correspond plus au rendu courant : c'est
exactement la définition de « synchronisé » ici.

`POST /citations/reconcile` aligne les lignes sur les nœuds du document après chaque
autosave : il est **idempotent** (un nœud déjà enregistré est mis à jour, pas dupliqué) et
marque en suppression douce les lignes dont le nœud a disparu, pour que leur snapshot
survive.

## Versioning et autosave

Les citations vivent dans `Section.content`, donc l'autosave existant les persiste et chaque
modification produit une `section_revision` comme le reste du document. Aucun chemin
d'écriture parallèle n'a été ajouté.

`SectionRevision.content` est un **snapshot complet** du document : un nœud `citation` y
conserve son `citationId` et ses `referenceIds`. Si une référence disparaît plus tard, une
ancienne révision reste lisible grâce à `citations.snapshot_text`.

## Permissions

| opération | reader | editor | owner |
|---|---|---|---|
| lister / lire / `/citations/rendered` / `/bibliography/rendered` | oui | oui | oui |
| `/citations/styles`, `/citations/preview` | oui | oui | oui |
| créer / modifier / `reconcile` / `detach-reference` / `bibliography/refresh` | 403 | oui | oui |
| supprimer une citation | 403 | 403 | oui |

Toutes les mutations exigent CSRF, y compris `preview` (qui n'écrit rien) : la règle « tout
POST est protégé » ne laisse pas de cas ambigu. Le câblage des rôles est vérifié par test sur
la route elle-même.

## Sécurité

* `POST /citations` valide que chaque `reference_id` appartient au projet ; une référence d'un
  autre projet répond **404**, pas un message qui révélerait son existence ;
* un `reference_id` malformé est abandonné, jamais deviné en une référence au hasard ;
* `_validate_references` refuse une citation sans aucune référence ;
* les listes sont bornées (`MAX_REFERENCES_PER_CITATION = 20`, `MAX_RENDER_REFERENCES = 1000`,
  longueurs de champs par le schéma) ;
* `importBibliographyFile` reste protégé comme à l'étape 9.

## Séparation RAG / bibliographie

Deux concepts distincts, deux tables, aucun mélange :

```text
RAG (étape 7)      assistant_citations   →  [SRC-001]   provenance d'un passage
Académique (10)    citations / citation_items → (Dupont, 2024)
```

`CitationItem` n'a ni `chunk_id` ni `document_id` : il ne peut pas pointer vers un chunk RAG.
L'assistant de rédaction garde son interdiction de produire une citation ou une référence, et
le pipeline `writing` n'expose toujours aucune fonction d'écriture de section. **Le modèle
propose, l'auteur décide** : l'étape 10 n'accorde aucun droit d'insertion à l'IA.

## Limites assumées

* `duplicates_of` / la numérotation comparable balayent au plus 200 / l'ensemble du document ;
  au-delà, la détection et la numérotation sont partielles.
* `is_orphaned` est un indice mis en cache, recalculé à chaque lecture ; il ne doit pas être
  lu directement comme une vérité.
* La variante ISO 690 author-date n'est pas implémentée.
* L'aperçu d'un style numérique avant enregistrement ne peut pas connaître le numéro définitif,
  car celui-ci dépend de l'ordre de citation dans tout le document ; le style le signale
  (« numéro non attribué ») au lieu d'inventer un numéro.
