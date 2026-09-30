# Guide d'utilisation

Ce document suit le parcours réel d'un auteur de mémoire, dans l'ordre où il le rencontre.
Il décrit ce que l'application fait, et surtout **où l'auteur tranche**.

## Le principe qui gouverne tout

> **L'IA propose, l'auteur décide.**

Aucun texte généré n'est écrit dans le mémoire. Une proposition de rédaction, une réponse
d'assistant, un plan : tout est une suggestion que l'auteur accepte, modifie ou rejette dans
l'éditeur. Rien n'est appliqué automatiquement.

Corollaire : l'audit **signale**, il ne réécrit pas. Une étiquette dit « à vérifier », elle ne
corrige pas la phrase.

## 1. Créer un compte

`/register` — adresse et mot de passe. Le premier compte créé n'est **pas** administrateur :
l'attribution est un acte explicite (voir `installation.md`).

## 2. Se connecter

`/login`. La session repose sur un cookie `HttpOnly` ; le jeton CSRF est transmis en en-tête.
Un mot de passe est hashé (Argon2), jamais stocké en clair.

Connexion Google possible si `GOOGLE_CLIENT_ID` et `GOOGLE_CLIENT_SECRET` sont configurés.

## 3. Créer un mémoire

`/projects/new` — titre, sujet, problématique, objectifs. Ces éléments ne sont pas décoratifs :
ils servent de contexte à l'assistant et de référence à l'audit.

## 4. Ajouter des sources

`/projects/{id}/sources` — glisser-déposer ou sélection. Formats acceptés : PDF, DOCX, TXT,
Markdown, CSV, XLSX, images.

À l'import, l'application :

1. stocke le fichier binaire ;
2. extrait le texte **avec provenance** — chaque fragment sait d'où il vient, page et position ;
3. signale les doublons avant de les traiter.

Les sources sont des **documents de travail**. Elles ne sont pas des références
bibliographiques : une référence est une œuvre citée dans le mémoire, une source est un document
consulté. Les deux notions sont distinctes dans le code et dans l'interface.

## 5. Interroger ses sources (RAG)

`/projects/{id}/rag` — indexation par fragments, recherche hybride (sémantique et lexicale),
filtres. Chaque résultat affiche sa **chaîne de provenance complète** : source, page, fragment.

Les citations du RAG sont notées `[SRC-001]` et reliées à leur source. Ce ne sont pas des
citations académiques : une citation académique renvoie à une référence de bibliographie.

## 6. Assistant académique

`/projects/{id}/assistant` — question posée sur les sources. La réponse cite `[SRC-001]`.
L'assistant ne répond pas sans contexte récupéré : sans source pertinente, il le dit.

## 7. Rédaction assistée

`/projects/{id}` — l'éditeur. Le panneau de rédaction propose des actions (structuration,
rédaction à partir des sources). Chaque action renvoie une **proposition** avec sa provenance
et son coût.

Appliquer une proposition est un geste explicite de l'auteur. Le backend n'écrit jamais dans le
mémoire : l'invariant est vérifié par un test qui interdit l'accès en écriture depuis le
pipeline de rédaction.

## 8. Bibliographie

`/projects/{id}/bibliography` — références, auteurs, tags. Styles gérés :

| Style | Particularité |
|---|---|
| APA 7 | auteur-date |
| Harvard | auteur-date, variante |
| Vancouver | numérotation, ordre d'apparition |
| ISO 690 | numérotation |

La numérotation suit l'ordre de **première citation** dans le document, pas l'ordre de saisie.

## 9. Citations

Insérer une citation dans le texte crée un nœud réel dans l'éditeur, pas du texte formaté. Une
citation orpheline (citée mais absente de la bibliographie) est signalée par l'audit.

## 10. Audit académique

`/projects/{id}/audit` — 23 contrôles **déterministes, sans modèle de langage** :

- cohérence entre problématique, objectifs et contenu ;
- citations orphelines, références non citées ;
- structure du mémoire, sections vides ;
- langue, typographie, cohérence terminologique ;
- statistiques du mémoire, tendance dans le temps ;
- préparation de soutenance.

Étiquettes canoniques : `Non renseigné`, `À vérifier`, `Source insuffisante`. L'audit ne
modifie rien.

## 11. Export

Export PDF et DOCX. Le document produit comprend couverture, sommaire, listes des figures et
tableaux, pagination romaine puis arabe, en-tête courant, bibliographie puis annexes.

Les images distantes sont **refusées par défaut** : aller chercher une URL fournie par un
auteur est un vecteur SSRF. L'activation de l'option ne suffit pas, les adresses privées
restent refusées.

## 12. Console d'administration

`/admin` — réservée aux administrateurs. Liste des comptes, suspension, attribution du
privilège d'administration, journal des décisions. Toute action est tracée avec son auteur.

Un administrateur ne peut pas se suspendre ni se révoquer lui-même.

## Ce que l'application ne fait pas

- Elle n'écrit rien dans le mémoire sans validation de l'auteur.
- Elle ne réécrit pas le texte lors d'un audit.
- Elle n'invente pas de source, de citation ou de référence.
- Elle ne confond jamais une source de travail et une référence bibliographique.
- Elle ne contacte aucun service externe sans que l'appel soit mesuré, limité et journalisé.
