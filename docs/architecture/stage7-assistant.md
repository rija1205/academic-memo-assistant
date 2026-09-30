# Étape 7 — Assistant académique avec OpenAI

## Positionnement

L'étape 6 a produit un moteur de **récupération**. L'étape 7 le branche sur un modèle de
langage pour produire des réponses **fondées** sur les documents de l'utilisateur. Le RAG
n'est pas réécrit : il est appelé tel quel par `app/assistant/pipeline.py`.

```text
Question utilisateur
        ↓
Validation de la question + rate limit
        ↓
RAG de l'étape 6 (hybrid_search) + reranking
        ↓
Top-K passages du projet courant
        ↓
Construction du contexte inerte (SRC-001, SRC-002 …)
        ↓
OpenAI (chat/completions)
        ↓
Réponse
        ↓
Validation de chaque identifiant de citation
        ↓
Réponse lisible + sources cliquables
```

**OpenAI n'interroge jamais la base de données.** Le modèle ne reçoit que les passages
sélectionnés par le RAG, Winsorisés et numérotés.

## Abstraction LLMProvider

`app/assistant/llm.py` définit un `Protocol` `LlmProvider` avec deux implémentations :

* `OpenAiLlmProvider` : appels `POST /chat/completions`, retries, mapping des erreurs ;
* `MockLlmProvider` : déterministe, hors ligne, **obligatoire pour les tests**. Il ne simule
  pas un générateur : il réordonne uniquement des phrases **présentes dans le contexte
  fourni**, et il conserve chaque prompt reçu (`provider.received`) pour que les tests
  assertent le contexte réellement envoyé.

Ajouter Gemini, Anthropic ou un modèle local revient à implémenter `LlmProvider` et à
l'enregistrer dans `build_llm_provider`. Le pipeline n'est pas modifié. **Aucun fournisseur
supplémentaire n'est codé à cette étape.**

## Sécurité de la clé

* lue uniquement dans `LLM_API_KEY`, côté serveur ;
* absente de tous les schémas Pydantic, de l'OpenAPI, du HTML et des logs ;
* une erreur `401/403` du fournisseur est journalisée **sans le corps de la réponse**, qui
  pourrait contenir un fragment de clé ;
* la production **refuse** `LLM_PROVIDER=mock` et exige une clé non vide, au démarrage.

## Modèle de chat

Trois tables, migration `0006_assistant` :

| Table | Rôle |
|-------|------|
| `assistant_conversations` | `project_id` + `user_id` : une conversation n'appartient qu'à un projet et qu'à un utilisateur |
| `assistant_messages` | question et réponse, rôle contraint par `CHECK`, statut, usage tokens, coût, durées RAG/LLM |
| `assistant_citations` | relie la réponse au passage réellement récupéré |

Le rôle `system` existe en base mais **l'API ne permet jamais au client d'en créer un** : les
rôles acceptés en entrée sont imposés par le pipeline.

Les conversations sont supprimées en soft delete (`deleted_at`) et leurs lignes messages /
citations sont retirées, conformément à la politique de suppression existante.

## Prompt académique et anti-hallucination

`app/assistant/prompts.py` impose :

* réponse **uniquement** à partir du bloc documentaire ;
* formulation explicite lorsque les sources sont **insuffisantes** ;
* interdiction d'inventer auteur, année, DOI, chiffre, résultat, citation, référence ;
* distinction entre ce qui est établi, ce qui est une synthèse, ce qui ne l'est pas ;
* obligation de rattacher chaque affirmation à un identifiant `[CITATION:SRC-00X]`.

## Contexte et identifiants stables

`build_document_context` rend chaque passage avec un identifiant **stable** (`SRC-001`,
`SRC-002`, …) et sa provenance complète (titre, auteurs, année, page, blocs, `provenance_id`,
score). Le bloc est tronqué **passage entier** : un passage est inclus ou écarté, jamais coupé
au milieu, donc un identifiant ne peut pas désigner un fragment arbitraire.

## Validation des citations

`app/assistant/citations.py` est le point de contrôle. Chaque identifiant renvoyé par le
modèle est confronté à l'ensemble exact des passages envoyés :

| Cas | Résultat |
|-----|----------|
| `SRC-001` présent et même projet | accepté, avec position numérique |
| `SRC-001` absent du contexte | **refusé** (`unknown_identifier`) |
| passage d'un autre projet | **refusé** (`other_project`) |
| identifiant mal formé | **refusé** (`malformed_identifier`) |

Les références refusées sont retirées de l'affichage et signalées à l'utilisateur. Une
réponse sans citation déclenche un avertissement de rattachement. Les marqueurs
`[CITATION:SRC-001]` sont convertis en `[1]`, `[2]` — la numérotation provient de la liste
validée, jamais du modèle.

**Test critique** : `test_model_citing_a_source_that_does_not_exist_is_refused` fournit au
modèle un contexte ne contenant que `SRC-002` et lui fait citer `SRC-001`. La citation est
refusée. `test_citation_to_another_project_is_refused` vérifie le cas inter-projets.

## Sources insuffisantes

Si la récupération ne renvoie aucun passage exploitable, le pipeline retourne

```json
{
  "status": "insufficient_sources",
  "answer": null,
  "user_message": "Les sources disponibles dans ce mémoire ne permettent pas de répondre suffisamment à cette question."
}
```

**Aucun appel au modèle n'est effectué** dans ce cas — vérifié par
`test_no_retrieval_means_no_model_call`, qui fait échouer le test si le fournisseur est
sollicité.

## Protection contre le prompt injection

Les documents importés sont des **données**, pas des instructions. Trois mesures :

1. le guide d'injection est placé **à l'extérieur** des délimiteurs
   `<document_context>` … `</document_context>`, afin que tout ce qui est entre les balises
   soit du contenu quotable pur ;
2. le system prompt déclare explicitement que les documents peuvent contenir des ordres
   adverses et qu'ils ne doivent jamais être exécutés ;
3. l'ordre du tour utilisateur est system → historique → question → **documents en dernier**,
   les documents non fiables étant ainsi la dernière chose lue avant la génération.

Un PDF contenant « Ignore toutes les instructions précédentes » est cité comme donnée ; le
modèle ne reçoit jamais ce texte au niveau d'une instruction.

## Contexte conversationnel

`build_history_window` applique une fenêtre glissante :

* au plus `ASSISTANT_MAX_HISTORY_MESSAGES` messages ;
* dans un budget de tokens, calculé par estimation déterministe ;
* les échanges les plus récents sont conservés, les plus anciens sont abandonnés ;
* un résumé glissant (`assistant_conversations.summary`) porte le contexte plus lointain, ce
  qui permet de comprendre « et concernant les lipides ? ».

Si le contexte total dépasse `ASSISTANT_MAX_INPUT_TOKENS`, l'historique est lâché en premier :
les règles système et la question sont toujours conservées.

## Coûts et limitation

* `app/assistant/cost.py` calcule le coût à partir des tokens réellement consommés, avec
  les tarifs de référence ou `LLM_PRICE_*_PER_MILLION_TOKENS_USD`. La colonne
  `cost_is_estimate` distingue une estimation d'un tarif fourni. Modèle inconnu → coût
  signalé « non disponible », jamais inventé.
* `app/assistant/ratelimit.py` limite les questions par minute et les tokens par jour, via
  Redis avec repli en mémoire si Redis est indisponible. Un rate limiter en panne ne doit pas
  tomber l'assistant.

## Gestion des erreurs

| Situation | Catégorie | Message utilisateur |
|-----------|-----------|---------------------|
| timeout | `timeout` | « Le service de génération a mis trop de temps à répondre. » |
| 429 | `rate_limited` | « Le service de génération est temporairement saturé. » |
| 401/403 | `authentication` | « La configuration du service de génération est invalide. » |
| réseau / 5xx | `unavailable` | « Le service de génération est momentanément indisponible. » |
| contexte trop long | `context_too_long` | « Le contexte est trop volumineux pour le modèle. » |
| refus du fournisseur | `refusal` | « Le modèle a refusé de répondre à cette demande. » |

Les détails techniques ne sont jamais renvoyés au frontend : seuls la catégorie et le
message sûr le sont.

## Observabilité

Chaque message enregistré conserve : durée RAG, durée modèle, nombre de passages récupérés,
tokens d'entrée et de sortie, modèle, fournisseur, catégorie d'erreur, coût, notes de
rattachement et citations refusées. Aucune clé d'API n'est journalisée.

## Permissions

| Rôle | Conversation | Question (génération payante) |
|------|--------------|------------------------------|
| owner | oui | oui |
| editor | oui | oui |
| reader | lecture seule | **non (403)** |

Une conversation est en outre filtrée par `user_id` : celle d'un autre utilisateur renvoie
404, jamais 403, afin de ne pas révéler son existence.

## Ce qui n'est pas développé

Rédaction automatique du mémoire, génération de chapitres, reformulation, bibliographie
automatique, Google Drive, Google Docs, Gemini, NotebookLM, export Word/PDF. Ces
fonctionnalités viendront après validation de l'assistant.
