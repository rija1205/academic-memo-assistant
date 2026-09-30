# Étape 11 — Export académique PDF / DOCX

## Principe directeur

**L'export ne réécrit jamais une citation.** Le texte de chaque citation et de la bibliographie
vient du moteur de l'étape 10, lu en base au moment de l'export. Il n'existe qu'une seule
implémentation de la logique bibliographique dans le projet, et les deux formats la
consomment.

```text
Section.content (Tiptap JSON)
        ↓  TiptapConverter
 blocs neutres  ← citationId → texte du moteur de l'étape 10
        ↓
 ┌──────────────┴──────────────┐
 render_pdf                render_docx
 (reportlab)               (python-docx)
```

Le texte d'affichage stocké dans le nœud n'est utilisé que si le serveur ne connaît pas encore
le nœud — le bloc est alors marqué `pending` et les deux rendus l'annoncent à l'auteur.

## Le modèle neutre

`app/export/blocks.py` définit des blocs sans dépendance à reportlab ni à python-docx :
`HEADING`, `PARAGRAPH`, `CITATION`, `FIGURE`, `TABLE`, `EQUATION`, `LIST`, `QUOTE`, `CODE`,
`TOC`, `COVER`, `BIBLIOGRAPHY`, `PAGE_BREAK`. C'est ce qui permet d'ajouter un troisième
format (LaTeX, HTML, texte brut) sans toucher à la logique.

Un `Span` porte le texte et ses marques. Un span qui est le rendu d'une citation porte aussi
son `CitationState` (`is_orphaned`, `is_pending`, `warnings`) : c'est ce qui permet
d'annoter **à l'endroit exact** une citation douteuse, même quand elle est au milieu d'un
paragraphe.

## Cohérence des citations

Trois dispositions, chacune testée :

1. le texte vient du serveur : `(Dupont, 2024, p. 25)` dans l'éditeur, `(Dupont, 2024, p. 25)`
   dans le PDF et le DOCX ;
2. une citation dont la référence a été supprimée s'affiche
   `[Citation invalide : référence introuvable]` et n'est **jamais** complétée par un auteur
   plausible ;
3. un nœud de l'ancienne version (étape 3, clé libre `Auteur2025`) est signalé comme non
   enregistré, avec une consigne de rattachement.

## Rendu PDF (reportlab)

Conventions académiques implémentées :

* couverture sans numéro de page ; pages liminaires en chiffres romains ; corps en chiffres
  arabes redémarrant à 1 ;
* titres numérotés (`I.`, `1.1`) et signets PDF ;
* table des matières construite depuis les sections **réellement présentes** ;
* liste des figures et liste des tableaux ;
* figures légendées et numérotées, tableaux avec ligne d'en-tête répétée ;
* en-tête courant suivant le titre de la page courante, pas le dernier titre du document ;
* bibliographie en retrait négatif, annexes placées après ;
* page A4 ou Letter, portrait ou paysage, marges, police et interligne configurables.

Deux mise en œuvre méritent d'être signalées parce qu'elles ne sont pas évidentes :

* l'en-tête courant et le redémarrage de la numérotation utilisent un **flowable marqueur** de
  taille nulle. L'en-tête doit être connu au moment du *tracé* de la page, alors que toute la
  liste de flowables existe avant la première page. Une simple affectation pendant
  l'assemblage ferait afficher le dernier titre sur toutes les pages ;
* le marqueur de début de corps est **ponctuel** : un saut de page à l'intérieur du corps ne
  doit pas déplacer le point de redémarrage, sinon la numérotation recommence deux fois.

## Rendu DOCX (python-docx)

* styles `Heading N` natifs : le volet de navigation et la table automatique de Word
  fonctionnent ;
* champ `TOC` Word réel, **plus** une liste des sections écrite en clair, pour que le document
  reste lisible avant que Word ne mette le champ à jour ;
* vraies listes, vrais tableaux avec bordures, vraies images ;
* numéros de page par codes de champ `PAGE` ;
* métadonnées académiques dans les propriétés du document (titre, auteur, mots-clés,
  établissement, année) ;
* document modifiable dans Word et LibreOffice.

## Images

L'éditeur stocke les images sous forme d'URL, ce qui fait de l'export un risque d'injection
de requête serveur. Les règles sont strictes :

| source | traitement |
|---|---|
| `data:` | décodée et intégrée, taille bornée à 12 Mo |
| `http(s)` | refusée **par défaut** ; si `EXPORT_ALLOW_REMOTE_IMAGES=true`, l'hôte est résolu et chaque adresse obtenue est vérifiée (privée, loopback, link-local, multicast, réservée ⇒ refus) |
| `blob:`, `file:`, `javascript:` | toujours refusées |
| autre | refusée |

Une image non intégrable produit un **encadré visible** dans le PDF et une note dans le DOCX,
jamais un silence. `EXPORT_ALLOW_REMOTE_IMAGES` ne suffit pas à désactiver la protection : les
adresses privées restent refusées.

## Couverture et structure

La couverture ne contient que des champs réellement renseignés : titre, sous-titre, auteur,
établissement, niveau, type de mémoire, encadreur, année universitaire, mots-clés. Un champ
absent produit un avertissement dans l'aperçu, jamais une invention.

La problématique, l'objectif général et les objectifs spécifiques suivent la couverture quand
ils existent.

## Table des matières

Construite depuis `sections` joined to `outline_nodes` : la profondeur vient de la véritable
hiérarchie du plan, et non d'un niveau supposé. Une section sans titre n'apparaît pas. Les
annexes sont détectées par leur titre (`Annexe…`) ou par un titre réduit à une lettre, et
sortent après la bibliographie.

## Numérotation des titres

Calculée une seule fois, dans `compute_headings`, donc identique dans les deux formats :

* niveau 1 : romains (`I.`, `II.`…) ;
* niveaux 2 et 3 : décimaux (`1.1`, `2.1.3`) ;
* seuls les niveaux réellement présents contribuent une partie, pour ne jamais afficher `0.0.1` ;
* les niveaux sont bornés à 6, ce qu'acceptent les deux rendus.

## API

| Route | Rôle | Rôle requis |
|---|---|---|
| `GET /exports` | historique du projet | reader |
| `GET /exports/formats` | formats, polices, valeurs par défaut, limites | reader |
| `GET /exports/{id}` | une trace d'export | reader |
| `POST /exports/preview` | ce que l'export contiendrait | reader + CSRF |
| `POST /exports/{format}` | génère le fichier | **editor** + CSRF |

Générer un export produit un fichier : c'est traité comme une action mutante, avec CSRF, et la
trace est écrite dans `document_exports`. Le nom de fichier est assaini : un titre contenant
`../../` ou un guillemet ne peut ni injecter un en-tête ni sortir du dossier.

## Limites

* `EXPORT_ALLOW_REMOTE_IMAGES` est lu par la configuration mais le rendu se base sur l'option
  `embed_remote_images` de la requête, elle-même bornée par le schéma : la variable sert de
  garde-fou documentaire, la décision reste explicite par export.
* La table des matières du PDF est une liste de titres avec signets, sans numéros de page
  calculés. Le champ `TOC` du DOCX, lui, est calculé par Word à l'ouverture. Les deux sont
  exacts quant au contenu, mais seul le DOCX affiche des numéros de page automatiques.
* Les équations sont rendues comme du texte, sans moteur LaTeX.
* Les listes à plusieurs niveaux n'ont pas de numérotation hiérarchique.
