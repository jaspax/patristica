# Infrastructure

Production host (#117, #132): one DigitalOcean droplet running Postgres 16 with pgvector, the FastAPI app (`api/`), the Next.js web app (`web/`) and Caddy for TLS, plus nightly database dumps to DigitalOcean Spaces. It also holds the public Spaces bucket and CDN that serve the static library to the web app (#131). Everything is code. The only manual steps are creating the DigitalOcean account and token and generating the SSH key.

| Piece | Where | What it does |
|---|---|---|
| `tofu/` | OpenTofu | Creates the droplet (`m-2vcpu-16gb-intel`, memory-optimized, `nyc3`), a 40 GB volume for the Postgres data, a reserved IP, a firewall, the backups bucket and its access key, the library bucket with its CORS rule, CDN and upload key, and a project. State lives in the Spaces bucket `patristica-tfstate`. |
| `tofu/cloud-init.yaml` | first boot | Installs Docker, rclone and unattended-upgrades. Adds 4 GB of swap, turns off SSH passwords and mounts the volume at `/mnt/pgdata`. It contains no secrets. |
| `compose/` | the droplet | Runs `db` (pgvector/pgvector), `api` (built from `api/Dockerfile`), `web` (built from `web/Dockerfile`) and `caddy` (ports 80/443, Let's Encrypt). Postgres has no published port. |
| `deploy.sh` | your machine, CI | Syncs `compose/` and the API and web source to `/opt/patristica`, writes the host's `.env`, installs the backup timer and the prewarm unit, runs `docker compose up --build` and loads the search index into the page cache. Idempotent. With `--keep-env` it leaves the host `.env` alone and needs no tofu: the *Deploy* workflow runs it that way. |
| `tofu.sh` | your machine | Runs `tofu` with the credentials from `infra/.env`. |

Prerequisites on your machine: `tofu` 1.13 ([OpenTofu](https://opentofu.org/docs/intro/install/)), `uv`, `ssh`, `rsync`, `curl`.

## First-time setup

1. **DigitalOcean**: create an account and a personal access token. Use full access, or custom scopes: `droplet`, `block_storage`, `firewall`, `reserved_ip`, `ssh_key`, `spaces_key` and `cdn` (create/read/update/delete each), `project` (the same plus `assign_resource`), `block_storage_action:create` and `block_storage_action:read`, and `regions:read`, `sizes:read`, `image:read`, `actions:read`. Spaces buckets don't use the token; they use the Spaces keys. A missing scope shows up as a 403 naming it on the first `tofu plan`, and you can edit a token's scopes in place. Then:
   ```bash
   cp infra/.env.example infra/.env     # gitignored; set DIGITALOCEAN_TOKEN
   ```
2. **Deploy key**: generate a key just for this server, and keep the private half in the password manager:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/patristica_deploy -C patristica-deploy
   ```
   To work from another machine, restore the key there. Set `PATRISTICA_SSH_KEY` in `infra/.env` if it lives somewhere other than `~/.ssh/patristica_deploy`.
3. **State bucket**: this creates a Spaces key for OpenTofu, saves it to `infra/.env`, and creates the `patristica-tfstate` bucket (versioned):
   ```bash
   uv run --extra deploy python -m scripts.bootstrap_infra
   ```
4. **Provision**: running `apply` starts billing: the droplet + ~$4 volume + $5 Spaces. The plain `m-2vcpu-16gb` is $84/mo; the API doesn't list the `-intel` variant's price, so read it on the DigitalOcean Create screen.
   ```bash
   infra/tofu.sh init
   infra/tofu.sh plan
   infra/tofu.sh apply
   ```
5. **Deploy**: when it finishes, it checks `https://api.patristica.app/healthz`, `https://patristica.app/` (plus `/api/healthz`) and `https://www.patristica.app/` (add the DNS records first; see "Changing the host").
   ```bash
   infra/deploy.sh
   ```

## Day to day

- **Deploy changes**: merging to `master` deploys them (see "Deploy workflow"). To deploy by hand, or after a change that adds a setting to the host `.env`, run `infra/deploy.sh`.
- **Shell**: `$(infra/tofu.sh output -raw ssh_command)`, then run `cd /opt/patristica/compose && docker compose ps` / `logs`.
- **psql**: `ssh -i ~/.ssh/patristica_deploy root@<ip> 'cd /opt/patristica/compose && docker compose exec db psql -U patristica'`.
  - For a local client, publish nothing. Tunnel to the container instead: find its address with `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' patristica-db-1`, then `ssh -L 5432:<that ip>:5432 …`.
  - The password is `POSTGRES_PASSWORD` in `/opt/patristica/compose/.env` (a symlink to `/mnt/pgdata/compose.env`). It is generated on the droplet the first time and never leaves it.
- **Run the stack locally** over plain HTTP:
  ```bash
  cd infra/compose && cp .env.local.example .env && docker compose up -d --build --wait
  curl http://localhost:18080/                # web app
  curl http://localhost:18080/api/healthz     # API through the web app's origin
  curl http://api.localhost:18080/healthz     # API on its own hostname
  ```

## Web app

The Next.js app (`web/`, #132) runs as the `web` service, built from `web/Dockerfile` with `output: "standalone"`. Caddy serves it on the apex `patristica.app`, and `www.patristica.app` redirects there permanently, keeping the path.

- **`/api/*` on the apex goes to the FastAPI app, with the prefix stripped** by Caddy (`handle_path`): `https://patristica.app/api/search` reaches the API as `/search`, the same route as `https://api.patristica.app/search`. So FastAPI routes are declared without `/api`, the browser calls the API same-origin with no CORS (`NEXT_PUBLIC_API_URL=/api`, #142), and the Next.js app must not define its own routes under `/api`. `api.patristica.app` stays for health checks and direct use.
- `NEXT_PUBLIC_LIBRARY_URL` is inlined into the client bundle at build time, so it is a build argument (`LIBRARY_URL` in the host `.env`, from `infra/tofu.sh output -raw library_url`), not a runtime setting. Changing it means rebuilding the image, which `infra/deploy.sh` does.
- The hostnames are `WEB_DOMAIN` (default `patristica.app`) and `WWW_DOMAIN` (`www.` + it) in the host `.env`, written by `infra/deploy.sh`. Locally they are `http://localhost` and `http://www.localhost` (`.env.local.example`).
- The image is built on the droplet during `docker compose up --build`, like the API's. Docker's layer cache keeps a deploy without dependency changes to the `next build` step.
- There are no preview deploys: PRs are checked by CI only (lint, typecheck, tests, build, and a build of the image).

## Deploy workflow

`.github/workflows/deploy.yml` runs `infra/deploy.sh --keep-env` on every push to `master` that touches `web/`, `api/`, `patristica/`, the Python lock files, `compose/` or `deploy.sh`, and on demand (Actions → Deploy → Run workflow). It syncs the code and runs `docker compose up --build`, then checks the same URLs as a manual deploy. It never touches the host `.env`, so a change that needs a new setting there (for example an API key) needs one manual `infra/deploy.sh` run first; otherwise compose stops with "set … in .env".

It needs three repo secrets. Add them once, without printing them:

```bash
infra/tofu.sh output -raw ip | gh secret set DEPLOY_HOST
gh secret set DEPLOY_SSH_KEY < ~/.ssh/patristica_deploy
ssh-keyscan -t ed25519 "$(infra/tofu.sh output -raw ip)" | gh secret set DEPLOY_KNOWN_HOSTS
```

Check the scanned key against the one you already trust (`ssh-keygen -F <ip>` in `~/.ssh/known_hosts`). After rebuilding the droplet, its host key changes: update `DEPLOY_KNOWN_HOSTS`. Until all three secrets exist, the workflow only prints a warning.

## Library

The static library export (`scripts.export_library`) is served from the Spaces bucket `patristica-library` through its CDN, https://patristica-library.nyc3.cdn.digitaloceanspaces.com. The web app's `NEXT_PUBLIC_LIBRARY_URL` is that URL (`infra/tofu.sh output -raw library_url`).

- The bucket listing is private. `scripts.upload_library` uploads each file gzipped and public-read, and keeps its change manifest `_manifest.json` private. The CORS rule (GET/HEAD from any origin) is part of the tofu config.
- The CDN caches each file for `library_cdn_ttl` seconds (600), so `index.json` can be up to 10 minutes stale after a publish.
- The library is published by `scripts.pipeline` as its last step (#248), not by a GitHub workflow. It uploads with a Spaces key that can only touch this bucket. Put it in `web/.env` (gitignored) once after the first `apply`, with `LIBRARY_BUCKET=patristica-library`, without printing it:
  ```bash
  { echo "LIBRARY_ACCESS_KEY_ID=$(infra/tofu.sh output -raw library_access_key)"
    echo "LIBRARY_SECRET_ACCESS_KEY=$(infra/tofu.sh output -raw library_secret_key)"
    echo "LIBRARY_BUCKET=patristica-library"; } >> web/.env
  ```
- To publish without the rest of the pipeline, run `uv run --extra deploy python -m scripts.upload_library` after `scripts.export_library` (`--dry-run` first).
- The bucket has no `prevent_destroy`: everything in it is rebuilt from `data/normalized` by one publish run.

## Backups

`patristica-backup.timer` runs `compose/backup/pg-backup.sh` every night at 03:30 UTC. It streams a `pg_dump --format=custom` to `spaces:patristica-backups/pg-backups/` under a timestamped name. The bucket's lifecycle rule deletes dumps after 15 days (`backup_keep_days`). The droplet's Spaces key can only touch that bucket. The dump reads the whole database through the page cache, so the script runs `compose/postgres/prewarm.sh` at the end, whether the dump succeeded or not.

- Run one now: `systemctl start patristica-backup && journalctl -u patristica-backup`.
- List them: `cd /opt/patristica/compose && set -a && . ./.env && rclone lsl spaces:$BACKUP_BUCKET/pg-backups/`.
- Restore one, on the droplet: copy the dump into a scratch database first, never straight over production:
  ```bash
  cd /opt/patristica/compose && set -a && . ./.env && set +a
  docker compose exec -T db createdb -U patristica restore_test
  rclone cat spaces:$BACKUP_BUCKET/pg-backups/<name>.dump \
    | docker compose exec -T db pg_restore -U patristica -d restore_test --no-owner
  ```

The dumps hold the 512-dim vectors the database keeps. The full 1024-dim vectors (`data/embeddings/`) live only on the machine that ran `scripts.embed` until they are archived (#156); restoring a dump needs no re-embedding, but rebuilding with more dims does.

## Search API

`GET /search` (`api/search.py`, #141) embeds each query with Voyage, so the `api` container needs `VOYAGE_API_KEY`. `deploy.sh` writes it to the host `.env`, taking it from the environment, `infra/.env` or the repo-root `.env`. The Deploy workflow (`--keep-env`) doesn't touch the host `.env`, so after adding or changing the key run `infra/deploy.sh` once by hand. Without the key `/search` answers 503 and everything else works.

- Optional host `.env` settings: `SEARCH_RATE_PER_MINUTE` (default 30) and `SEARCH_BURST` (10) per client IP, and `SEARCH_EF_SEARCH` (100).
- Every query not in the in-memory cache is a paid Voyage call (a few tokens). The cache is lost on restart.
- Each search logs its embedding and database time (`docker compose logs api | grep search:`).

## Search index

`scripts.build_index` (#137) loads works, chunks, translations and vectors into the database (schema and tables: `db/README.md`). Postgres has no public port, so run it from your machine through `db-tunnel.sh`. The tunnel forwards a local port to the db container and gives the command `DATABASE_URL` and `PGPASSWORD`. It reads the password from the host `.env` and never prints it:

```bash
infra/db-tunnel.sh uv run --extra index python -m scripts.build_index --dry-run
infra/db-tunnel.sh uv run --extra index python -m scripts.build_index --embeddings-dir <path to data/embeddings>
infra/db-tunnel.sh psql
```

- It needs `data/normalized` (tracked), `data/translations` (tracked) and `data/embeddings` (from `scripts.embed`, gitignored).
- The first load copies about 4 GB of vectors (binary COPY, ~1 KB a vector) and then builds the HNSW index on the droplet with `maintenance_work_mem = 4GB` (`--maintenance-work-mem`). Later runs reload only works whose inputs changed and insert into the live index. A run that changes most of the corpus is faster with `--rebuild-index`.
- Each work is its own transaction, so an interrupted run picks up where it stopped. The index is built at the end of a run, so after an interruption run it again to completion.
- A change of Scripture verse groups (`patristica/versification.py`) only updates `chunks.translation_group_id` in place; the summary line counts the chunks "regrouped in place". The first run after #186 also rewrites each work's stored hash to the new format ("format-1 hashes rewritten") and reloads nothing; check with `--dry-run` that it reports 0 loaded.
- After the index build, load it into the page cache: on the droplet, `/opt/patristica/compose/postgres/prewarm.sh` (or `systemctl start patristica-prewarm`). See "Postgres sizing".
- Passage alignments (`data/alignments/`, #179) go into `passage_groups` in place, like the verse groups: the summary counts the "passage-group rows synced" and nothing is reloaded. The table is new in #179; `db/schema.sql` creates it on the first run (no schema version change). The first full run writes about 1.34M rows in 442k groups (roughly 250 MB with its indexes), one transaction per work; computing them takes about 15 s. Check with `--dry-run` that it reports 0 loaded.
- The keyword index for quoted search (#86) needs every chunk's `text_folded`. The first run after it was added folds the loaded chunks in place from the local normalized files (no vectors are reloaded), sending about 650 MB, then builds `chunks_text_folded_trgm` (about 650 MB). The `UPDATE` rewrites every chunk row, so `chunks` temporarily takes about twice its size on the volume.

## Postgres sizing

The droplet is memory-optimized, `m-2vcpu-16gb-intel` (#252): the search load is bound by memory and I/O, not CPU. `compose/postgres/postgresql.conf` is tuned for its 16 GB with the ~5.2 GB HNSW index (`chunk_vectors_hnsw_m1`, 512-dim `halfvec`, ~4.0M vectors; ~1.3 GB more per million vectors):
- `shared_buffers=4GB`, with the OS page cache holding the index (`effective_cache_size=12GB`). That keeps the index cached up to roughly 7–8M vectors.
- `pg_prewarm.autoprewarm` reloads the buffers after a restart.
- `compose/postgres/prewarm.sh` loads every `chunk_vectors_hnsw_m*` index, `chunks_pkey` and `passage_groups_pkey` into the OS page cache with `pg_prewarm(…, 'prefetch')`. It runs at boot (`patristica-prewarm.service`, installed by `deploy.sh`), after every deploy and after the nightly backup. It is idempotent, returns at once (the kernel reads ahead in the background) and warms nothing on a database without the indexes yet. Its output: `journalctl -u patristica-prewarm`. `free -g` shows the index under `buff/cache` once it is read.

With the index cached, `build_index` inserts into the live index at ~130 vectors/s instead of ~12/s from the network volume (#249, #252), so routine loads insert into it. Keep `--rebuild-index` for one-off giant batches (#200), since it takes search down while the index is rebuilt.

`build_index` builds the index with `maintenance_work_mem = 4GB` (`--maintenance-work-mem`); on this droplet up to `8GB` is reasonable for a full rebuild (`--rebuild-index --maintenance-work-mem 8GB`). By hand, in that session only: `SET maintenance_work_mem = '8GB'; SET max_parallel_maintenance_workers = 1;` (2 vCPU). A parallel build keeps that memory in the db container's `/dev/shm`, so `shm_size` in `compose/docker-compose.yml` (9 GB) must stay larger than `maintenance_work_mem`. Otherwise the build fails with `could not resize shared memory segment … No space left on device` (#166), which is about shared memory, not the disk. The containers have no memory limits; during an 8 GB build, the index isn't in use and the page cache gives way.

### Changing the droplet size

A memory-optimized droplet has a 50 GB root disk, and DigitalOcean can't shrink a disk on resize, so moving between it and a Basic size with a larger disk (the old `s-4vcpu-8gb` had 160 GB) is a **replacement**, not a resize. Tofu is set up for that: the volume (`prevent_destroy`) holds the database and the host `.env` (`/mnt/pgdata/compose.env`, with `POSTGRES_PASSWORD`), the new droplet gets it at creation and cloud-init mounts it at `/mnt/pgdata`, and the reserved IP is reassigned. 50 GB is enough for the root disk: it holds the OS and the Docker images only.

The changeover from `s-4vcpu-8gb` (#252) goes in this order, because merging anything under `infra/compose/` deploys it: the 16 GB Postgres settings must not reach the 8 GB droplet. Expect 10–20 minutes of downtime.

1. **Quiesce.** No `build_index` or pipeline run in progress. Note the time.
2. **Fresh backup.** On the droplet, `systemctl start patristica-backup.service`, and check that the dump landed in `patristica-backups/pg-backups/` (see "Backups"). Optionally take a volume snapshot in the DigitalOcean panel.
3. **Stop the stack cleanly** on the droplet, so Postgres shuts down before the volume detaches: `docker compose -f /opt/patristica/compose/docker-compose.yml down`.
4. **Replace.** With the size change in your working tree (`droplet_size` in `tofu/variables.tf`; tofu applies from the working tree, not from `master`), run `infra/tofu.sh plan -replace=digitalocean_droplet.db` and check that it replaces only the droplet (and updates the reserved-IP assignment, firewall and project), **never the volume**. Then `infra/tofu.sh apply -replace=digitalocean_droplet.db`.
5. **Host key.** `ssh-keygen -R 159.89.246.34`, scan the new key and update the `DEPLOY_KNOWN_HOSTS` repo secret (see "Deploy workflow"). The Deploy workflow fails until then.
6. **Deploy with the old settings** from `master`: `infra/deploy.sh --keep-env` with `DEPLOY_HOST`, `API_DOMAIN` and `WEB_DOMAIN` set (the host `.env` is the volume's `compose.env`, so it is already there). The images are rebuilt on the new droplet and the site is back up.
7. **Merge the held PR** with the 16 GB settings. Its automatic deploy brings the Postgres settings and the prewarm. Merging it before step 4 would put 16 GB settings on the 8 GB droplet.
8. **Verify.** `https://api.patristica.app/healthz`; `infra/db-tunnel.sh uv run python -m scripts.status --db` (`index_meta` intact, nothing to load); a cold search (the API log's `search:` line) and the warm timing; `journalctl -u patristica-prewarm` lists the indexes and `free -g` shows them in `buff/cache`.
9. **Reload rate.** On the next pipeline run, compare `build_index`'s vectors/s with the old ~12.
10. **Clean up.** The replace destroys the old droplet; delete any manual snapshot after a few days. The new droplet gets the backup timer from `deploy.sh`: check it with `systemctl list-timers`.

**Rollback:** if the new droplet misbehaves, revert `droplet_size` (and the Postgres settings, through a PR, before or after as in steps 4–7 above) and `-replace` again; the volume and the IP move back the same way. If the database itself is damaged, restore the step-2 dump (see "Backups").

## Changing the host

- `cloud-init.yaml` and the base image only apply when the droplet is created, so changing them doesn't replace the droplet. To change the size, see "Changing the droplet size". To rebuild on purpose, run `infra/tofu.sh apply -replace=digitalocean_droplet.db`, then `infra/deploy.sh`. The data volume (with the database and the host `.env`, `/mnt/pgdata/compose.env`) and the reserved IP survive. The host key changes, so remove the old entry from `~/.ssh/known_hosts` first: `ssh-keygen -R <ip>`.
- The volume and the backups bucket have `prevent_destroy`, so `tofu destroy` stops at them. To tear everything down, remove that line on purpose first.
- The API hostname is `api.patristica.app` (`api_domain`). The domain is registered at Cloudflare and its DNS is managed by hand there: an A record to the reserved IP, **DNS only** (not proxied), so Caddy can get its Let's Encrypt certificate. To change it, update the record, set `api_domain`, then run `infra/tofu.sh apply` and `infra/deploy.sh`. An empty `api_domain` falls back to `<ip-with-dashes>.sslip.io`.
- The web app's hostnames are the apex `patristica.app` and `www.patristica.app`: two more A records to the reserved IP, also **DNS only**. To use another name, run `WEB_DOMAIN=<name> infra/deploy.sh` (and change `WEB_DOMAIN` in the Deploy workflow, which uses it for its health checks). Proxying them through Cloudflare later would need SSL mode *Full (strict)* and a certificate that works behind the proxy (a DNS-01 challenge or a Cloudflare Origin CA certificate); see #132.
