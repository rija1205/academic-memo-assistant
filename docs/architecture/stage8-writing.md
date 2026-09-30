# Étape 8 — Rédaction académique assistée

## Positionnement

L'étape 7 répond à des questions. L'étape 8 transforme l'assistant en outil de rédaction : il
travaille sur le texte de l'auteur, sélectionné dans Tiptap.

**Règle non négociable : le modèle ne modifie jamais le mémoire.** Chaque action renvoie une
**proposition**. L'appliquer est une décision explicite de l'auteur, dans l'éditeur, via la
route de sauvegarde de section existante, qui conserve son contrôle de version optimiste et
son historique de révisions. Le pipeline n'expose aucune fonction d'écriture de section, et un
test le vérifie explicitement.

## Architecture

```text
Sélection Tiptap + instruction
        ↓
POST /projects/{id}/writing/generate
        ↓
Validation (action, sélection, section, limites)
        ↓
Rate limit partagé avec le chat (étape 7)
        ↓
RAG de l'étape 6 (uniquement si l'action utilise les sources) + reranking
        ↓
Contexte inerte SRC-xxx + texte de l'auteur
        ↓
OpenAI
        ↓
Validation des citations
        ↓
Proposition affichée : Insérer · Remplacer · Copier · Régénérer · Annuler
        ↓
Décision de l'auteur → l'éditeur applique → autosave existante
```

## Les douze actions

Le catalogue est déclaratif (`app/writing/actions.py`) : le frontend le récupère via
`GET /writing/actions` au lieu de coder une liste en dur.

| Action | Utilise les sources | Sélection requise |
|--------|----------------------|-------------------|
| `rephrase` Reformuler | non | oui |
| `correct` Corriger | non | oui |
| `academic_style` Style académique | non | oui |
| `summarize` Résumer | non | oui |
| `expand` Développer | non | oui |
| `condense` Réduire | non | oui |
| `translate` Traduire (→ anglais) | non | oui |
| `explain` Expliquer | **oui** | oui |
| `transition` Proposer une transition | non | oui |
| `analyze_section` Analyser la section | **oui** | section entière |
| `verify_claims` Vérifier les affirmations | **oui** | oui |
| `write_from_sources` Rédiger depuis les sources | **oui** | non |

Le choix est délibéré : **reformuler ou corriger n'utilisent pas les sources.** Réécrire la
phrase de l'auteur ne doit pas y glisser du matériel externe. Seules les actions qui portent
une affirmation scientifique vont chercher les documents du projet.

## Prompt

Chaque prompt d'action contient les règles absolues : production d'une proposition, aucune
écriture directe, aucune invention d'auteur, d'année, de DOI, de chiffre ou de référence, et
signalement explicite lorsque le texte est trop insuffisant.

Le tour utilisateur suit l'ordre : instruction de l'auteur → texte de l'auteur → **documents en
dernier**, les documents non fiables étant la dernière chose lue avant la génération. Le guide
d'injection reste à l'extérieur des délimiteurs `<document_context>`.

## Citations

La validation est celle de l'étape 7, réutilisée telle quelle : un identifiant absent du
contexte, mal formé ou appartenant à un autre projet est **refusé**, retiré de l'affichage et
signalé. Les marqueurs deviennent des numéros issus de la liste validée.

## Sources insuffisantes

Si l'action utilise les sources et que la récupération ne renvoie rien, la réponse est
`insufficient_sources` avec le message
« Les sources indexées de ce mémoire ne permettent pas de traiter cette demande. »
**Aucun appel au modèle n'est effectué** — vérifié par
`test_write_from_sources_without_context_returns_insufficient`.

## Modèles de données

Migration `0007_writing_assistant` :

* `writing_generations` : action, instruction, extrait de la sélection, texte proposé, statut,
  modèle, tokens, coût, durée RAG, citations refusées, note de rattachement, `applied_at` ;
* `writing_citations` : proposition → passage récupéré (source, fichier, chunk, provenance,
  page, extrait, score).

La clé étrangère vers `sections` est en `ON DELETE SET NULL` : supprimer une section ne détruit
pas l'historique de rédaction. L'historique est filtré par projet **et** par utilisateur.

## Coûts

Chaque proposition enregistre tokens d'entrée et de sortie, modèle, fournisseur, coût estimé et
le drapeau `cost_is_estimate`. Un modèle inconnu affiche « coût non disponible » plutôt qu'un
montant inventé.

## Ce que l'auteur peut faire

* **Insérer** : le texte de la proposition est inséré au curseur ;
* **Remplacer** : la sélection courante est remplacée (désactivé si rien n'est sélectionné) ;
* **Copier** : presse-papiers ;
* **Régénérer** : même action, même instruction ;
* **Annuler** : la proposition est effacée de l'écran et marquée `discarded` dans l'historique.

Aucune de ces actions n'écrit dans la base sans passer par l'autosave Tiptap existante.
