# Vote

Application web de sondages avec authentification Discord (OAuth2) et panneau d'administration réservé à une liste d'IDs Discord.

## Fonctionnalités

- Connexion via Discord OAuth2, sans mot de passe stocké côté application.
- Trois types de votes : note de 1 à 5, choix unique, choix multiple.
- Résultats agrégés par option, page de vote et page de résultats.
- Panneau d'administration : création, édition, activation et désactivation des votes, titre global du site.
- Un vote d'exemple est créé automatiquement au premier démarrage.

## Stack

Flask · SQLAlchemy (SQLite) · Jinja2 · python-dotenv · `uv` pour les dépendances et le lockfile.

## Configuration

Copier `.env_exemple` vers `.env`, puis renseigner :

| Variable | Rôle |
|---|---|
| `DISCORD_CLIENT_ID` | Client ID de l'application Discord utilisée pour l'OAuth2 |
| `DISCORD_CLIENT_SECRET` | Secret du client Discord |
| `DISCORD_REDIRECT_URI` | URL de retour autorisée dans l'application Discord (`http://localhost:5000/callback` en local) |
| `ADMIN_DISCORD_IDS` | IDs Discord autorisés à administrer les votes, séparés par des virgules |
| `SECRET_KEY` | Facultatif ; une clé aléatoire est générée au démarrage si absente |

## Lancer

```bash
uv sync
uv run main.py
```

L'application écoute sur `http://localhost:5000`.

## Structure

```
main.py              modèles, routes et enregistrement Discord
templates/           index, vote, résultats, administration
static/style.css     feuille de style
```

## Limites

- SQLite local, sans migrations : le schéma est créé au démarrage.
- Pas de tests automatisés.
- Le serveur de développement Flask est utilisé tel quel ; aucune configuration de déploiement n'est fournie.
