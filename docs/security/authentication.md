# Sécurité de l'authentification

## Sessions

- Le cookie `ama_session` est `HttpOnly`, `Secure` en production et `SameSite=Lax`.
- Le jeton brut n'est jamais stocké en base : seule son empreinte SHA-256 est conservée.
- Les sessions expirées ou révoquées sont rejetées côté API.
- Les sessions actives peuvent être listées et révoquées depuis les paramètres.

## CSRF

- Une requête `GET /api/auth/csrf` crée un cookie lisible par le frontend et renvoie le même jeton signé.
- Les requêtes modifiantes doivent envoyer `X-CSRF-Token`.
- La signature, l'expiration et la comparaison sont vérifiées côté backend.
- Le frontend utilise le proxy same-origin `/api/backend` afin que les cookies restent sur l'hôte de l'application.

## Limitation des tentatives

Les routes d'inscription, de connexion et de récupération utilisent une limitation Redis par empreinte IP + adresse. En production, une indisponibilité de Redis bloque ces opérations plutôt que de lever la protection.

## Mots de passe

- Argon2id via `argon2-cffi`.
- Les erreurs de connexion ne révèlent pas si une adresse existe.
- Les jetons de réinitialisation sont hachés, expirables et à usage unique.
- `AUTH_EXPOSE_RESET_TOKEN` doit rester `false` en production.
- Le transport d'email de récupération n'est pas encore intégré ; en développement, le jeton peut être exposé uniquement avec `AUTH_EXPOSE_RESET_TOKEN=true`.

## Google OAuth

- Scope limité à `openid email profile` pour cette étape.
- State signé et stocké dans un cookie HttpOnly.
- Nonce vérifié dans l'ID token.
- PKCE S256 utilisé.
- Les secrets Google restent exclusivement côté backend.
- Les tokens Google ne sont pas conservés à cette étape, car Drive/Docs n'est pas encore intégré.

## Projets

- Les mutations de contenu et de structure sont réservées aux rôles `editor` et `owner`.
- Les archives, suppressions et duplications sont réservées au propriétaire canonique.
- Les requêtes sont filtrées par `user_id` et par rôle de projet.
- Un projet appartenant à un autre utilisateur retourne `404`, afin de ne pas révéler son existence.
- Les permissions ne sont jamais estimées côté frontend uniquement.
- Les documents Tiptap sont validés et limités en taille/profondeur côté API.
- L'autosave utilise une version optimiste et renvoie `409` en cas de conflit.
- Une restauration crée une nouvelle révision immuable.

## Sources

- L'upload est limité par `SOURCE_MAX_UPLOAD_BYTES` et contrôlé par extension, MIME, signature et SHA-256.
- Les binaires sont hors PostgreSQL ; seules les métadonnées et la clé `StorageProvider` sont en base.
- Les clés de téléchargement sont vérifiées via les permissions du projet.
- `reader` ne peut ni télécharger, ni importer, ni modifier une source.
- Le callback worker exige `X-Worker-Token` et n'est pas destiné au navigateur.
- Le contenu extrait est conservé avec page, bloc, position et `provenance_id`.
