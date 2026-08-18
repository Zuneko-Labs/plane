# Plane Fork — Staging Deployment (`staging-deploy.sh`)

Server-specific deploy for the **staging box that already runs traefik** on ports 80/443/8080
(alongside erpnext, hmdm, postgres, etc.). Plane goes **live on a domain via that existing
traefik** — no port conflict, traefik terminates TLS and issues the cert.

- **Domain:** `plane.hourbeat.zunekolabs.tech`
- **Builds from your fork source** (`docker-compose.yml`) — custom code included.
- **Secrets baked as defaults** in `staging-deploy.sh` (SMTP app password) → the script is
  **git-ignored**, never committed. Move it to the server manually.

> General / portable install (any server, no traefik) = use `deploy.sh` + `DEPLOY.md`.
> This file is only for the staging server with traefik already present.

---

## How it avoids conflicts

| Concern | How it's handled |
|---------|------------------|
| 80/443 owned by traefik | Plane does **not** bind them. Joins traefik's network; traefik routes the domain to Plane's internal proxy (:80). Spare host ports `8090/8453` only for debug. |
| Other DB/redis on host | Plane runs its **own** `plane-db`, `plane-redis`, `plane-mq`, `plane-minio` in separate volumes under project `plane-staging`. No clash with erpnext/hmdm. |
| TLS cert | traefik's existing certresolver issues it automatically. |
| Volume name clashes | Project name `plane-staging` prefixes all volumes. |

---

## What the script does

`detect_traefik` finds, automatically:
- traefik's **docker network** (network the traefik container is on),
- **entrypoint** + **certresolver** (read from existing traefik-labeled containers; falls back
  to `websecure` / `letsencrypt`).

Then it:
1. Bootstraps `.env` files + `SECRET_KEY`.
2. Writes domain URLs into `apps/api/.env` + `apps/web/.env`, SMTP into `apps/api/.env`.
3. Generates `docker-compose.staging.yml` (traefik labels + external network).
4. Builds your fork and starts everything on the traefik network.

---

## Editable configuration

Top of `staging-deploy.sh`:

```bash
DOMAIN="plane.hourbeat.zunekolabs.tech"
CERT_EMAIL="nilesh.p@zuneko.in"
SMTP_HOST="smtp.gmail.com"
SMTP_PORT="587"
SMTP_USER="nilesh.p@zuneko.in"
SMTP_PASS="****************"       # Gmail App Password (spaces removed)
SMTP_FROM="nilesh.p@zuneko.in"
SMTP_TLS="1"; SMTP_SSL="0"

TRAEFIK_NET=""            # auto-detected; set manually if detection is wrong
TRAEFIK_ENTRYPOINT=""     # auto-detected (default websecure)
TRAEFIK_CERTRESOLVER=""   # auto-detected (default letsencrypt)
HTTP_PORT="8090"; HTTPS_PORT="8453"
```

You can change credentials **two ways**:
- Edit the top of the script → `./staging-deploy.sh apply`
- Or edit `apps/api/.env` directly → `./staging-deploy.sh apply` (+ `smtp-sync` if SMTP changed)

---

## Deploy steps (staging server)

**1. DNS** — `plane.hourbeat.zunekolabs.tech` A record → server public IP (`76.13.240.193`).

**2. Clone your fork:**
```bash
ssh root@76.13.240.193
git clone git@github.com:Zuneko-Labs/plane.git
cd plane
git checkout preview
```

**3. Put the staging script on the server** (it's git-ignored, so not in the clone):
```bash
# from your local machine:
scp staging-deploy.sh root@76.13.240.193:/root/plane/
```
(or paste it into a new file on the server)

**4. Fix line endings + run:**
```bash
cd /root/plane
sed -i 's/\r$//' staging-deploy.sh
chmod +x staging-deploy.sh
./staging-deploy.sh first
```

First build: 10–20 min. When done, traefik routes the domain; open
`https://plane.hourbeat.zunekolabs.tech`. First signup = admin. Admin panel: `/god-mode`.

---

## Commands

```bash
./staging-deploy.sh first        # env + detect traefik + build + up  (first run)
./staging-deploy.sh update       # git pull + rebuild + up (NO data loss)
./staging-deploy.sh apply        # re-apply .env / top-of-script edits + recreate
./staging-deploy.sh smtp-sync    # push SMTP env changes into the DB
./staging-deploy.sh test-email   # send a test email
./staging-deploy.sh status
./staging-deploy.sh logs
./staging-deploy.sh start | stop | restart
./staging-deploy.sh backup       # dump Postgres -> backup-plane-staging-*.sql
./staging-deploy.sh destroy      # DELETE all staging data (confirm-gated)
```

---

## Data safety

- Volumes: `pgdata`, `uploads`, `redisdata`, `rabbitmq_data` under project `plane-staging`.
- `update` / `apply` use `docker compose up -d` (never `-v`) → data preserved.
- Only `destroy` runs `down -v` (requires typing `DELETE`).
- **Do not change `PROJECT_NAME`** in the script after first deploy (orphans volumes).

---

## SMTP behaviour

Plane seeds SMTP env into the DB on **first boot** only (`configure_instance` = `get_or_create`);
runtime reads from the DB, editable in **god-mode → Email**.

- First deploy: SMTP from script → `apps/api/.env` → seeded into DB.
- Change later: god-mode UI, **or** edit `apps/api/.env` + `./staging-deploy.sh smtp-sync`.
- Gmail needs an **App Password** (not the account password).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No running traefik container found` | traefik not up, or use `deploy.sh` standalone instead |
| Domain not routing | traefik must use the **docker provider** (labels). Check traefik dashboard `:8080`. |
| Wrong network detected | Set `TRAEFIK_NET` at top of script → `./staging-deploy.sh apply` |
| No TLS cert | Set correct `TRAEFIK_CERTRESOLVER` + ensure DNS resolves → `apply` |
| `\r command not found` | `sed -i 's/\r$//' staging-deploy.sh` |
| Emails not sending | `./staging-deploy.sh test-email`; check god-mode → Email or run `smtp-sync` |
| Custom code missing | It builds from source; run `./staging-deploy.sh update` |

---

## Files

| File | Committed? | Purpose |
|------|:--:|---------|
| `staging-deploy.sh` | ❌ git-ignored (secrets) | The staging deploy script |
| `docker-compose.staging.yml` | ❌ generated | traefik labels + external network |
| `backup-plane-staging-*.sql` | ❌ | DB dumps |
| `STAGING.md` | ✅ | This guide (no secrets) |
