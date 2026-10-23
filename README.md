# BookFlow

**Prise de rendez-vous en ligne multi-entreprises (SaaS) : réservation, paiement, rappels et tableau de bord.**

![CI](https://github.com/MohamedAnasBenMim/bookflow/actions/workflows/ci.yml/badge.svg)

Un salon, un studio de yoga ou un cabinet publie sa page `bookflow/<entreprise>` ; ses clients choisissent
une prestation et un créneau, paient en ligne et reçoivent une confirmation puis un rappel la veille.
Le gérant suit ses rendez-vous, ses prestations, ses horaires et son équipe depuis un tableau de bord.

| Page de réservation | Rendez-vous confirmé |
|---|---|
| ![Réservation](docs/screenshots/booking-page.png) | ![Confirmation](docs/screenshots/booking-confirmed.png) |

![Tableau de bord du gérant](docs/screenshots/dashboard.png)

## Ce qui rend le projet intéressant

Une application de réservation paraît simple. Les vraies difficultés sont ailleurs, et chacune est traitée
et **testée** ici :

| Problème réel | Solution | Preuve |
|---|---|---|
| **Double réservation** : deux clients cliquent sur le même créneau à la même milliseconde | Contrainte d'exclusion PostgreSQL `EXCLUDE USING gist (staff_id WITH =, tstzrange(start_at, end_at) WITH &&)` : l'impossibilité est garantie par la base, pas par le code | Test de charge : 100 clients simultanés sur 5 créneaux → **exactement 5 réservations, 95 refus propres (409), 0 erreur** |
| **Fuite de données entre entreprises** (multi-tenant) | **Row-Level Security** PostgreSQL (`FORCE`) : chaque transaction porte `app.tenant_id`, la base filtre elle-même toutes les lignes | Tests d'isolation ; les tests refusent de tourner avec un rôle superutilisateur (qui ignorerait le RLS) |
| **Paiement** : créneau bloqué par un client qui ne paie jamais, webhook reçu deux fois | Statut `pending_payment` expiré au bout de 15 min par le worker ; webhook Stripe **signé** et **idempotent** (table des événements traités) | Tests : signature invalide refusée, webhook rejoué sans effet, expiration |
| **Emails** perdus si le serveur SMTP tombe | Pattern **outbox** : notifications écrites dans la même transaction que la réservation, envoyées par un worker (`FOR UPDATE SKIP LOCKED`, 5 tentatives) | Tests de confirmation et de rappel |
| **Lenteur** de la page la plus consultée (calcul des créneaux) | Cache Redis versionné par entreprise, **zéro requête SQL** sur un succès de cache, invalidation **après commit** | k6 : **×3,2 en débit**, p95 ÷ 3,5 |

## Architecture

```
 Navigateur ──► Next.js 15 (Vercel) ──► API FastAPI ──► PostgreSQL 16 (RLS + contrainte d'exclusion)
                                             │   └────► Redis (cache des créneaux, limitation de débit)
 Stripe ──── webhook signé ─────────────────►┘
                                     Worker ──► expire les paiements en attente, envoie confirmations et rappels (outbox)
```

| Couche | Technologies |
|---|---|
| Backend | Python 3.12, **FastAPI**, SQLAlchemy 2, Alembic, Pydantic v2 |
| Données | **PostgreSQL 16** (RLS, `btree_gist`, `tstzrange`), **Redis 7** |
| Auth | JWT, mots de passe Argon2, **connexion Google** (vérification du jeton via les clés publiques Google) ; rôles propriétaire / admin / employé |
| Paiement | **Stripe Checkout** (mode test) ; fournisseur simulé pour la démo et la CI |
| Frontend | **Next.js 15** (App Router), React 19, TypeScript, Tailwind CSS v4 |
| Qualité | **pytest** (37 tests, **95 % de couverture**, vraie base PostgreSQL), **Playwright** (parcours de bout en bout), **k6** (charge), Ruff, ESLint |
| Ops | Docker, docker compose, GitHub Actions, Render (API + worker + Postgres + Redis) et Vercel, métriques **Prometheus** (`/metrics`), identifiant de requête `X-Request-ID` |

## Mesures de performance (k6)

Mesurées en local sur une machine partagée de **2 vCPU** (API : 2 workers uvicorn, PostgreSQL et Redis
sur la même machine) : les chiffres absolus sont modestes, ce sont les **écarts** qui comptent.

**Lecture des créneaux** (`loadtest/slots.js`, 50 utilisateurs virtuels, 30 s) :

| | Débit | Latence p95 | Échecs |
|---|---|---|---|
| Sans cache | 209,5 req/s | 381,6 ms | 0 % |
| **Avec cache Redis** | **670,8 req/s** | **107,8 ms** | **0 %** (20 190 requêtes) |

**Course aux créneaux** (`loadtest/booking.js`, 100 clients lancés simultanément sur 5 créneaux) :
5 réservations créées, 95 conflits renvoyés en `409`, 0 erreur, p95 789 ms ; en base, 5 rendez-vous
sur 5 horaires distincts.

## Deux bugs trouvés grâce aux tests de charge

**1. Un interblocage invisible dans les tests unitaires.** Au premier test de charge, 40 % des
réservations concurrentes restaient bloquées 30 s. Cause : la session SQL était une dépendance FastAPI
à `yield`, dont le commit s'exécute pendant le nettoyage, **dans un thread du pool**. Quand tous les threads
attendaient le verrou de ligne tenu par une transaction non validée, plus aucun thread ne pouvait la
valider. Correction : la transaction d'écriture est ouverte **et validée** dans l'appel lui-même
(`deps.public_tx`), avec `SET LOCAL lock_timeout` comme garde-fou (→ `409`). Résultat : 0 erreur.

**2. Une fenêtre de données périmées dans le cache.** Le cache était invalidé *avant* le commit : une
lecture concurrente pouvait recalculer les créneaux depuis l'ancien état et le remettre en cache.
L'invalidation passe désormais par l'événement SQLAlchemy `after_commit` (et est annulée sur
`after_rollback`).

## Démarrer en local

```bash
docker compose up --build
```

- Frontend : http://localhost:3000 — page publique de démo : http://localhost:3000/studio-zen
- API et documentation OpenAPI : http://localhost:8000/docs
- Compte de démo : `demo@bookflow.dev` / `demo1234` (ou bouton « Tester le tableau de bord » de l'accueil)

Le paiement est simulé par défaut. Pour Stripe en mode test :
`PAYMENTS_PROVIDER=stripe STRIPE_SECRET_KEY=sk_test_… STRIPE_WEBHOOK_SECRET=whsec_… docker compose up`,
puis `stripe listen --forward-to localhost:8000/webhooks/stripe`.

### Sans Docker

```bash
# PostgreSQL 16 + Redis 7 lancés, puis :
psql -U postgres -f deploy/init-db.sql          # rôle applicatif NON superutilisateur
cd backend && pip install -r requirements-dev.txt
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload                    # API
python -m app.worker                             # worker (autre terminal)
pytest --cov=app                                 # tests
cd ../frontend && npm ci && npm run dev          # frontend
npx playwright test                              # bout en bout (API lancée)
k6 run ../loadtest/slots.js                      # charge
```

## API

| Public (sans compte) | Administration (JWT + en-tête `X-Tenant`) |
|---|---|
| `GET /public/{slug}` — entreprise et prestations | `GET/POST/PATCH/DELETE /admin/services` |
| `GET /public/{slug}/slots?service_id&date` | `GET /admin/bookings` (pagination par curseur) |
| `POST /public/{slug}/bookings` (limité à 10/min/IP) | `POST /admin/bookings/{id}/cancel` |
| `GET /public/{slug}/bookings/{id}?token` | `GET/PUT /admin/availability` |
| `POST /public/{slug}/bookings/{id}/cancel?token` | `GET/POST /admin/staff` · `GET /admin/stats` |
| `POST /auth/register` · `/auth/login` · `/auth/google` · `GET /me` | `POST /webhooks/stripe` · `GET /health` · `GET /metrics` |

Un employé ne voit que ses propres rendez-vous ; seuls propriétaire et admins gèrent prestations et équipe.

## Déploiement

- **Render** : `render.yaml` décrit l'API, le worker, PostgreSQL et Redis (Blueprint).
- **Vercel** : racine `frontend/`, variable `NEXT_PUBLIC_API_URL`.
- La CI déclenche les deux déploiements après des tests verts si les secrets `RENDER_DEPLOY_HOOK_URL`
  et `VERCEL_DEPLOY_HOOK_URL` sont définis.

## Structure

```
backend/app/
  scheduling.py   calcul des créneaux, réservation concurrente, annulation, notifications
  db.py           sessions liées au tenant (RLS), invalidation du cache après commit
  cache.py        cache Redis versionné, limitation de débit (fenêtre glissante)
  payments.py     Stripe Checkout / fournisseur simulé
  worker.py       expiration des paiements, envoi des notifications (outbox)
  routers/        auth, public, admin, payments
backend/migrations/  schéma, contrainte d'exclusion, politiques RLS
backend/tests/       37 tests sur PostgreSQL et Redis réels
frontend/src/app/    page publique, suivi de réservation, connexion, tableau de bord
frontend/e2e/        Playwright
loadtest/            scénarios k6
```

## Licence

MIT — Mohamed Anas Ben Mim
