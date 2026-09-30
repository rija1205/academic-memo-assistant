# Étape 12 — Audit académique et contrôle de cohérence

## Principe

**L'audit signale, il ne répare pas.** Aucun contrôle ne modifie le mémoire, n'ajoute une
référence, ne complète un auteur ni ne réécrit une phrase. Chaque constat porte trois
informations : ce qui ne va pas, où le trouver, et ce que l'auteur doit décider de faire.

Trois étiquettes sont des valeurs à part entière, jamais des accidents de format :

| étiquette | quand |
|---|---|
| `Non renseigné` | une donnée est absente |
| `À vérifier` | un contrôle demande une confirmation humaine |
| `Source insuffisante` | un contrôle ne peut pas conclure faute de données |

## Déterminisme

L'audit est une fonction pure des données collectées. Aucun modèle de langage n'est appelé —
c'est vérifié par un test qui lit le source des modules et interdit `openai`, `llmprovider`,
`httpx`. Un audit dépendant d'un modèle ne pourrait pas être fiable pour produire deux fois la
même chose, et ne pourrait pas être testé.

Deux exécutions sur les mêmes données produisent le même rapport : un test le vérifie en
comparant les deux sorties après retrait de l'horodatage.

## Les 23 contrôles

**Cadrage** · métadonnées administratives manquantes (bloquant) · problématique absente
(bloquant) · objectif absent (bloquant) · hypothèses absentes (avertissement) · année
universitaire périmée · style bibliographique inconnu.

**Citations** · citations orphelines (bloquant) · citations sans référence (bloquant) ·
citations non enregistrées (avertissement) · citations répétées côte à côte (avertissement) ·
citations hors bibliographie (bloquant).

**Bibliographie** · références incomplètes, avec les champs manquants nommés · doublons
hérités de l'étape 9 · références jamais citées (information) · couverture bibliographique
faible.

**Sources** · source indexée sans provenance (bloquant) · source en erreur ou non indexée ·
référence ni consultable par DOI, ni par URL, ni par fichier.

**Structure** · sections vides · sections en cours · plan incomplet face au plan type ·
méthodologie, résultats ou conclusion non repérés · objectif sans section correspondante.

**Cohérence** · problématique et objectifs sans lien lexical · hypothèses sans résultats ni
conclusion.

## Le rendu des citations vient de l'étape 10

`_collect_citations` appelle `app.citations.service.render_citations` : le rapport décrit donc
exactement ce qu'un lecteur verra, et non une seconde interprétation. Un contrôle le vérifie en
interdisant l'import de `openai` dans le module.

## La comparaison des titres ignore les accents

Les titres sont normalisés (minuscules, sans accents) avant toute comparaison lexicale. Sans
cela, « Matériel et méthodes » ne correspondait pas à l'aiguille `materiel` et l'audit
annonçait une partie manquante dans un mémoire parfaitement structuré. C'est un bug réel,
trouvé par un test, qui aurait produit de faux avertissements sur tout mémoire français.

## Statistiques

`app/audit/statistics.py` calcule : structure (sections, chapitres, vides, complétées),
volume (mots, caractères, temps de lecture à 200 mots/minute, section la plus longue, moyenne),
citations (nombre, références distinctes, orphelines, non enregistrées, narratives, densité
pour mille mots), bibliographie (types, plage d'années, DOI, URL, non citées, plus citées),
sources (indexées, pages, blocs), matériel visuel (figures, tableaux, équations) et le détail
par section avec sa densité de citation.

Deux décisions :

* une densité de citation sur un mémoire vide vaut `None`, pas `0` : ce sont deux faits
  différents ;
* une référence citée mais absente de la bibliothèque **ne compte pas** dans les références
  distinctes, sinon une citation orpheline gonflerait le nombre d'ouvrages réellement cités.

Les observations de volume comparent aux normes déclarées (`Norms`) et sont formulées comme
des observations contextuelles, jamais comme un jugement de qualité.

## Pas de score inventé

Le rapport expose un *niveau* de préparation (`aucun_bloquant`, `corrections_requises`,
`reprise_necessaire`) et non un pourcentage. Un score laisserait croire à une précision que
les contrôles n'ont pas. Un test le vérifie. Quand aucun blocage n'est détecté, le niveau le
dit explicitement : « Cela ne vaut pas validation ».

## Préparation de la soutenance

La liste est une suite de **questions** à traiter par l'auteur, jamais d'actions. Elle est
construite à partir des données : les blocages d'abord, puis les avertissements, puis des
questions préparatoires dérivées des statistiques (densité faible, citations orphelines
visibles par le jury, section la plus longue). Les contrôles non concluants apparaissent avec
l'étiquette `Source insuffisante`.

## API

| Route | Rôle | Permission |
|---|---|---|
| `GET /audit` | lire le rapport | reader |
| `POST /audit/run` | exécuter l'audit, garder une trace si demandé | **editor** + CSRF |
| `GET /audit/traces` | historique et tendance | reader |
| `DELETE /audit/traces/{id}` | supprimer une trace | **owner** + CSRF |

Un `reader` peut **lire** l'audit : savoir ce qui manque n'est pas un privilège, et cacher
l'information ne ferait découvrir le problème qu'au pire moment. En revanche garder une trace
écrit, donc `editor`.

## Migration

`0011_academic_audit`, `down_revision = 0010_document_exports`. Table `academic_audits` :
niveaux de préparation, compteurs, mots, citations, références, findings en JSON, durée.
**Aucun texte du mémoire n'y est copié** — les findings sont la sortie propre de l'audit, pas le
contenu de l'auteur.

## Limites

* La détection des parties attendues est lexicale et prudente : l'absence d'un titre ne prouve
  pas l'absence d'une partie, et le message le dit.
* La cohérence problématique/objectifs est également lexicale : deux formulations ou
  cohérentes mais sans mot commun sont signalées comme une *vérification*, pas comme une
  erreur.
* L'audit ne lit pas le sens des phrases : il ne détecte ni une contradiction interne, ni un
  plagiat, ni une faiblesse d'argumentation.
* La tendance de progression n'est calculée qu'à partir de deux traces au minimum.
