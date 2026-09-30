# Étape 9 — Bibliographie et références académiques

## Positionnement

L'étape 9 introduit le gestionnaire bibliographique. Il s'appuie sur ce qui existe
(projets, sources, permissions) et n'en modifie pas le comportement.

La séparation conceptuelle est explicite et appliquée dans le modèle :

```text
Source documentaire        fichier importé, extrait, indexé par le RAG
        ↓ (lien optionnel)
Référence bibliographique  travail intellectuel, avec ou sans fichier
        ↓ (étape 10)
Citation dans le mémoire
        ↓
Bibliographie finale
```

**Une source importée n'est pas une référence, et une référence n'est pas une source.**
Le lien est optionnel et unidirectionnel : la référence ne recopie pas les métadonnées de la
source, ce qui évite de stocker deux fois la même information, et supprime le fichier source
ne détruit pas la référence.

## Modèle de données

Migration `0008_bibliography` :

| Table | Rôle |
|-------|------|
| `bibliographic_references` | l'enregistrement, avec DOI canonique + DOI d'origine, champs de publication, `source_id` optionnel |
| `reference_authors` | auteurs relationnels : `position`, `given_name`, `family_name`, `orcid` |
| `reference_tags` | tags du projet, uniques par projet |
| `reference_tag_links` | relation plusieurs-à-plusieurs |

Une table `bibliographic_authors` séparée n'a pas été créée : un auteur est toujours relatif à
une référence et l'ordre est porteur de sens. Une table de personnes globale auraitAllowi la
fusion accidentelle de deux homonymes entre projets.

Champs enregistrés : type, titre, sous-titre, auteurs, année, mois, jour, DOI, URL, date
d'accès, revue, volume, numéro, pages, éditeur, lieu, édition, ISBN, ISSN, résumé, mots-clés,
langue, notes, champs inconnus, clé de citation, type d'entrée d'origine.

## Types de référence

`article`, `book`, `book_chapter`, `thesis`, `report`, `conference`, `webpage`, `dataset`,
`patent`, `other`. Le mapping est une table, donc ajouter un type ne demande qu'une entrée de
plus. Un type inconnu dans un fichier importé devient `other` et **le type d'origine est
conservé** dans `entry_type` : l'information n'est pas perdue.

## Métadonnées : jamais d'invention

Règle appliquée partout : un champ absent reste `NULL` en base et s'affiche « Non renseigné »
dans l'interface. Aucun modèle de langage n'est appelé pour compléter une référence, ni pour
l'import, ni pour la recherche. Un fichier BibTeX sans année produit une référence sans année.

## Normalisation du DOI

Formes équivalentes ramenées à la forme canonique :

```text
10.1234/example
https://doi.org/10.1234/example
https://dx.doi.org/10.1234/example
doi:10.1234/example
```

Le DOI canonique sert à la comparaison et à la détection de doublons. Le DOI **d'origine** est
conservé séparément pour ne rien détruire.

Les URL sont normalisées sans être cassées : schéma et hôte en minuscules, port par défaut
retiré, chemin et chaîne de requête intacts. Une URL qui n'est pas `http`/`https` est
refusée plutôt que réécrite — `javascript:alert(1)` ne devient jamais une URL interrogeable.

## Auteurs

Parsing des deux conventions réelles : `Dupont, Jean` (BibTeX/RIS) et `Jean Dupont`.
`Jean Paul Dupont` devient famille `Dupont`, prénoms `Jean Paul`. Un nom ambigu n'est jamais
éclaté deviné : un seul token reste un nom de famille sans prénom.

## Doublons

Trois niveaux, du certain au possible :

* **exact** : même DOI canonique ;
* **fort** : même titre normalisé et même année ;
* **possible** : similarité de titre (coefficient de Dice sur les tokens, seuil 85 %) et au
  moins un nom de famille commun.

La similarité est calculée en Python pur, donc explicable : le rapport affiche la raison et
le score utilisés. **Jamais de suppression automatique.** L'auteur fusionne, conserve les
deux, ou ignore.

Une fusion ne perd rien : les champs absents sont repris du doublon, les auteurs et les tags
sont **déplacés** et non remplacés, les mots-clés sont unis, les notes sont concaténées, et le
doublon est marqué supprimé (soft delete) pour rester auditable.

## Import

### BibTeX

Analyse lexicale par **appariement d'accolades**, pas par expression régulière paresseuse : un
article, une résumé ou une commande imbriquée ne terminent donc plus l'entrée trop tôt. Une
entrée aux accolades non équilibrées est signalée, sans planter. Les champs inconnus sont
conservés dans `extra_fields`, ce qui stabilise l'aller-retour.

Le contenu est traité comme du **texte** : aucune entrée n'est évaluée, exécutée ou
interprétée. Un titre contenant `$(rm -rf /)` ou `__import__("os")` reste une chaîne.

### RIS

`TY`, `AU`, `TI`, `PY`, `JO`, `VL`, `IS`, `SP`, `EP`, `DO`, `UR`, `PB`, plus `T2`, `CY`,
`AB`, `KW`, `LA`, `N1`, `SN`, `ID`, `Y2`. Les tags répétés (`AU`, `KW`) sont accumulés et
l'ordre est préservé. `SN` est interprété : `ISBN …` et `ISSN …` deviennent deux champs
distincts, et l'export réécrit le préfixe pour que le réimport soit exact.

### Limites

`BIBLIOGRAPHY_MAX_IMPORT_BYTES` (2 Mo par défaut) sur la taille du fichier,
`BIBLIOGRAPHY_MAX_IMPORT_ENTRIES` (2000) sur le nombre d'entrées, et une longueur maximale par
champ validée par le schéma. Un import trop volumineux renvoie `413`.

## Export et aller-retour

Export BibTeX avec échappement des caractères spéciaux (`&`, `%`, `$`, `#`, `_`, `{`, `}`) et
export RIS. Un test vérifie le cycle **import → export → import** pour les deux formats et
contrôle que le type, le titre, l'année, la revue, le volume, le numéro, les pages, le DOI,
l'ISSN, les mots-clés et l'ordre des auteurs sont conservés.

## Recherche

SQL direct sur titre, revue, DOI, éditeur, résumé, mots-clés et clé de citation, plus un filtre
auteur sur `reference_authors`. **Aucun appel au RAG, aucun appel à un modèle de langage.**
Un index GIN full-text (`simple`) est créé par la migration sur ces champs.

## Liaisons avec les sources

`source_id` est optionnel. Une référence peut n'avoir aucun fichier local, ce qui est le cas
normal d'un ouvrage cité sans l'avoir téléchargé. La référence peut aussi pointer vers une
source du projet ; le contrôle vérifie que la source appartient bien au projet, donc pas de
liaison croisée. La clé étrangère est en `ON DELETE SET NULL`.

## Permissions

| Rôle | Lire / rechercher / exporter | Créer / modifier / importer / fusionner | Supprimer |
|------|-------------------------------|--------------------------------------|-----------|
| reader | oui | non (403) | non (403) |
| editor | oui | oui | non (403) |
| owner | oui | oui | oui |

Toute requête est filtrée par `project_id`. Une référence d'un autre projet renvoie `404`.

## Préparation pour l'étape 10

Le modèle est prêt pour la chaîne demandée : `BibliographicReference` porte une
`citation_key` stable, les auteurs sont ordonnés et structurés, et l'export BibTeX/RIS fournit
les champs dont un style bibliographique a besoin. L'insertion de citations dans Tiptap n'est
**pas** développée ici.

## Ce qui n'est pas développé

Citations intégrées dans l'éditeur, styles APA / Vancouver / Harvard / IEEE, génération
automatique de la bibliographie finale. Ces éléments relèvent de l'étape 10.
