# Plane Fork — Deployment Guide (`deploy.sh`)

Portable deploy for **your fork** (`git@github.com:Zuneko-Labs/plane.git`) on **any** Docker
server. Images build **from your source**, so custom changes (e.g. team-calendar in
`apps/api/plane/app/urls/workspace.py`) run in production.

Plane runs its **own proxy (Caddy)** on ports you choose — no external proxy (nginx/traefik)
required. Works on a clean VPS or alongside other apps by picking free ports.

> Uses root `docker-compose.yml` (build from source).
> **Never** use `deployments/cli/community/docker-compose.yml` — that pulls prebuilt
> `makeplane/*` images and ignores your code.

---

## What `deploy.sh` does

| Job | Detail |
|-----|--------|
| **Env bootstrap** | Creates every `.env` from `.env.example` + generates `SECRET_KEY`. |
| **First-deploy prompts** | Access URL, ports, TLS mode, SMTP. |
| **Apply config** | Writes URLs into `apps/api/.env` + `apps/web/.env`; ports + TLS into root `.env`; SMTP into `apps/api/.env`. |
| **Build / run** | Compiles your fork into images, starts all services. |
| **Update** | `git pull` → rebuild → recreate — **no data loss**. |
| **Reconfigure** | Change URL/ports/SMTP later, rebuild + restart. |
| **Ops** | SMTP re-sync, test email, status, logs, start/stop/restart, backup, host inspect. |

---

## Data safety (no data loss)

Data lives in named volumes: `pgdata`, `uploads`, `redisdata`, `rabbitmq_data`.

- Update/rebuild use `docker compose up -d` (never `-v`) → containers recreate, volumes stay.
- Fixed project `-p plane` → volume prefix constant. **Do not change `PROJECT_NAME`** after first deploy.
- Only **DESTROY** runs `down -v` (requires typing `DELETE`).

---

## Ports & TLS (portable)

Plane's Caddy proxy routes one origin by path: `/api /auth /static` → api,
`/god-mode` → admin, `/spaces` → space, `/live` → live, `/uploads` → minio, `/` → web.

At first deploy you choose:

- **Access URL** — how users reach it: `http://<ip>:<port>` (testing) or `https://<domain>`.
- **HTTP / HTTPS host ports** — which host ports the proxy binds.
- **TLS mode:**
  - `none` — plain HTTP. Use for testing, custom ports, or when another proxy sits in front.
  - `auto` — Caddy gets a free Let's Encrypt cert. Needs a **real domain**, host ports
    **80 AND 443 free**, and DNS pointing at the server.

**If ports 80/443 are already taken** (another app/proxy on the box), pick free ports
(default `8090/8453`) with TLS `none`, and reach Plane at `http://<ip>:8090`.
Run `./deploy.sh inspect` to see which ports are in use.

---

## First-time deploy

**Prereqs:** Docker + compose plugin, git, SSH deploy key for the fork, ~4 GB RAM.

```bash
# 1. Clone YOUR fork
git clone git@github.com:Zuneko-Labs/plane.git
cd plane
git checkout preview
chmod +x deploy.sh

# 2. (fallback) if bash complains about \r :
#    sed -i 's/\r$//' deploy.sh

# 3. See what ports are free (optional)
./deploy.sh inspect

# 4. Deploy
./deploy.sh            # menu -> 1   (first build 10-20 min)
```

Prompts:
- **Access URL** — e.g. `http://76.13.240.193:8090` (test) or `https://plane.zuneko.in`
- **TLS mode** — `1` none (test) or `2` auto (domain + 80/443 free)
- **Ports** — HTTP/HTTPS host ports (defaults sensible per mode)
- **SMTP** — `y` then host/port/user/app-password/from/TLS

First user to sign up = admin. Admin panel: `<url>/god-mode`.

---

## Example: this test server (76.13.240.193, ports 80/443 busy)

Another proxy already owns 80/443/8080, so run Plane on a free port, HTTP only:

```
Access URL : http://76.13.240.193:8090
TLS mode   : 1 (none)
HTTP port  : 8090
HTTPS port : 8453   (spare, just keep it free)
SMTP       : y (optional)
```

Open `http://76.13.240.193:8090`. Later, for a real domain with HTTPS: either switch to
TLS `auto` (needs 80/443 free) or put Plane behind the existing proxy pointing at `:8090`.

---

## SMTP behaviour (read this)

Plane seeds SMTP env into the **DB on first boot** (`configure_instance` = `get_or_create`).
Runtime reads SMTP from the DB (`SKIP_ENV_VAR=1`), editable in **god-mode → Email**.

- **First deploy:** SMTP prompts → `apps/api/.env` → seeded into DB. Works.
- **Change later:**
  - **god-mode UI** (`<url>/god-mode` → Email) — simplest, live.
  - **`./deploy.sh smtp-sync`** — clears SMTP rows, reseeds from `apps/api/.env`
    (use after editing env via `configure`).
- **Test:** `./deploy.sh test-email`.

Gmail: use an **App Password**, host `smtp.gmail.com`, port `587`, TLS `1`, SSL `0`.

---

## Update after pushing code

```bash
cd plane
./deploy.sh update      # git pull + rebuild + up, data preserved
```

---

## Menu / commands

Interactive: `./deploy.sh`

```
1) First-time deploy        7) Status
2) Update & redeploy        8) Logs
3) Configure URL/ports/SMTP 9) Start
4) Re-sync SMTP from env    10) Stop (keep data)
5) Send test email          11) Restart
6) Rebuild one service      12) Backup database
i) Inspect host ports
D) DESTROY (delete data)    0) Exit
```

Non-interactive (cron/CI):

```bash
./deploy.sh first | update | configure | smtp-sync | test-email \
           | stop | start | restart | status | logs | backup | inspect
```

---

## Generated files (git-ignored)

| File | Purpose |
|------|---------|
| `.deploy.conf` | Your non-secret answers (URL, ports, TLS mode). |
| `backup-plane-db-*.sql` | DB dumps (option 12). |
| `apps/*/.env`, `.env` | Env files (secrets — never commit). |
| `docker-compose.override.yml` | Only if you add one manually; auto-loaded if present. |

---

## `deploy.sh` vs `setup.sh`

| | `setup.sh` | `deploy.sh` |
|---|:--:|:--:|
| Copy `.env` files | ✅ (overwrites) | ✅ (keeps existing) |
| SECRET_KEY | ✅ | ✅ |
| `pnpm install` | ✅ | ❌ (build is in Docker) |
| URL / ports / SMTP prompts | ❌ | ✅ |
| Docker build (your image) | ❌ | ✅ |
| Update / lifecycle / backup | ❌ | ✅ |

- **VPS / Docker deploy** → `deploy.sh` only.
- **Local dev** (`docker-compose-local.yml` + `pnpm dev`) → `setup.sh`.

---

## Config knobs (top of `deploy.sh`)

```bash
REPO_URL="git@github.com:Zuneko-Labs/plane.git"
BRANCH="preview"                    # branch pulled on update
COMPOSE_FILE="docker-compose.yml"   # root = build from source
PROJECT_NAME="plane"                # volume prefix — DO NOT change after first deploy
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `\r command not found` | `sed -i 's/\r$//' deploy.sh` |
| `docker compose` not found | Install Docker Engine + compose plugin |
| Build OOM | ~4 GB RAM; add swap or bigger box |
| `port is already allocated` | Pick free ports (`./deploy.sh inspect`), or TLS `none` on custom port |
| No TLS cert (auto mode) | Domain must resolve to server + ports 80/443 free |
| Login/CORS errors | Wrong Access URL → `./deploy.sh configure` → restart |
| Emails not sending | `./deploy.sh test-email`; check god-mode → Email or run `smtp-sync` |
| Custom code missing | Confirm root `docker-compose.yml` + run `./deploy.sh update` |
