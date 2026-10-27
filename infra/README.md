# Infrastructure

Production host (#117, #132): one DigitalOcean droplet running Postgres 16 with pgvector, the FastAPI app (`api/`), the Next.js web app (`web/`) and Caddy for TLS, plus nightly database dumps to DigitalOcean Spaces. It also holds the public Spaces bucket and CDN that serve the static library to the web app (#131). Everything is code. The only manual steps are creating the DigitalOcean account and token and generating the SSH key.

| Piece | Where | What it does |
|---|---|---|
| `tofu/` | OpenTofu | Creates the database host in `droplet_region` (a 16 GB droplet, a 40 GB volume for the Postgres data and a reserved IP; during the #252 move also the old `nyc3` host, see "Moving the host"), a firewall, the backups bucket and its access key, the library bucket with its CORS rule, CDN and upload key (Spaces, in `region`, `nyc3`), and a project. State lives in the Spaces bucket `patristica-tfstate`. |
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
4. **Provision**: running `apply` starts billing: the droplet + ~$4 volume + $5 Spaces. The droplet's price depends on `droplet_size` (`m-2vcpu-16gb` is $84/mo); read any other size's price on the DigitalOcean Create screen, which also shows whether the region has it in stock (the API lists sizes it can't create).
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

The droplet has 16 GB (#252; `droplet_size`, e.g. `m-2vcpu-16gb`): the search load is bound by memory and I/O, not CPU. `compose/postgres/postgresql.conf` is tuned for 16 GB and 2 vCPU with the ~5.2 GB HNSW index (`chunk_vectors_hnsw_m1`, 512-dim `halfvec`, ~4.0M vectors; ~1.3 GB more per million vectors):
- `shared_buffers=4GB`, with the OS page cache holding the index (`effective_cache_size=12GB`). That keeps the index cached up to roughly 7–8M vectors.
- `pg_prewarm.autoprewarm` reloads the buffers after a restart.
- `compose/postgres/prewarm.sh` loads every `chunk_vectors_hnsw_m*` index, `chunks_pkey` and `passage_groups_pkey` into the OS page cache with `pg_prewarm(…, 'prefetch')`. It runs at boot (`patristica-prewarm.service`, installed by `deploy.sh`), after every deploy and after the nightly backup. It is idempotent, returns at once (the kernel reads ahead in the background) and warms nothing on a database without the indexes yet. Its output: `journalctl -u patristica-prewarm`. `free -g` shows the index under `buff/cache` once it is read.

With the index cached, `build_index` inserts into the live index at ~130 vectors/s instead of ~12/s from the network volume (#249, #252), so routine loads insert into it. Keep `--rebuild-index` for one-off giant batches (#200), since it takes search down while the index is rebuilt.

`build_index` builds the index with `maintenance_work_mem = 4GB` (`--maintenance-work-mem`); on this droplet up to `8GB` is reasonable for a full rebuild (`--rebuild-index --maintenance-work-mem 8GB`). By hand, in that session only: `SET maintenance_work_mem = '8GB'; SET max_parallel_maintenance_workers = 1;` (2 vCPU; 3 on a 4-vCPU size). A parallel build keeps that memory in the db container's `/dev/shm`, so `shm_size` in `compose/docker-compose.yml` (9 GB) must stay larger than `maintenance_work_mem`. Otherwise the build fails with `could not resize shared memory segment … No space left on device` (#166), which is about shared memory, not the disk. The containers have no memory limits; during an 8 GB build, the index isn't in use and the page cache gives way.

### Moving the host (#252)

The 8 GB `s-4vcpu-8gb` host in `nyc3` moves to a 16 GB droplet in another region (memory-optimized sizes had no capacity in `nyc3`). Candidates, in order: `sfo2` `m-2vcpu-16gb` ($84/mo), `nyc1` `s-4vcpu-16gb-320gb-intel`, `atl1` or `ric1` `g5-2vcpu-16gb-50gb`. A volume can't change region, so this is a **blue-green move**: the new host gets its own droplet, volume and reserved IP next to the old one, the database is restored from a dump, and DNS switches over. The old host serves until then, so there is no downtime; `build_index` and the pipeline are frozen from the dump until the switch.

How tofu models it (`tofu/main.tf`): hosts are keyed by region. `droplet_region` and `droplet_size` describe the new host. `keep_old_host` keeps the original `nyc3` host with its original resource names (`moved` blocks turn the old single-host resources into the `nyc3` entries without touching them). `serving_region` picks the host the outputs `ip` and `ssh_command` name, which `deploy.sh` and `db-tunnel.sh` read; `new_host_ip` is the new host's reserved IP and `host_ips` lists both. The firewall and the project cover every host. The Spaces buckets stay in `region` (`nyc3`), and so does the tfstate bucket; the host reaches them across regions. `tofu/tests/hosts.tftest.hcl` checks the layout against a mock provider (`tofu -chdir=infra/tofu test`).

The PR that brings the 16 GB settings is held: merging it auto-deploys to `DEPLOY_HOST`, and it must not put them on the 8 GB host. The new host gets them from the PR branch in step 3, and the PR is merged in step 11, after `DEPLOY_HOST` points to the new host. Run the steps from a checkout of the PR branch (tofu and `deploy.sh` use the working tree). Below, `OLD` is the old reserved IP (159.89.246.34), `NEW` is `infra/tofu.sh output -raw new_host_ip`, and `ssh OLD` / `ssh NEW` mean `ssh -i ~/.ssh/patristica_deploy root@<ip>`.

1. **Choose region and size.** On the DigitalOcean Create screen, find the first candidate in stock and note its price. Set `droplet_region` and `droplet_size` in `tofu/variables.tf` (commit to the PR). A day ahead, lower the TTL of the three Cloudflare A records (`patristica.app`, `www`, `api`; DNS only) from Auto (300 s) to 60 s.
2. **Create the new host.** `infra/tofu.sh plan` must show the `nyc3` droplet, volume, reserved IP and assignment as *moved* with no changes; creations of the new droplet, volume, reserved IP and assignment; in-place updates of the firewall and project; and **nothing destroyed**. Then `infra/tofu.sh apply`, and wait for cloud-init: `ssh NEW cloud-init status --wait`.
3. **Copy the host `.env`, then deploy.** The volume's `compose.env` holds `POSTGRES_PASSWORD` and must be there before Postgres initialises. Copy it host to host, without printing it:
   ```bash
   ssh OLD cat /mnt/pgdata/compose.env | ssh NEW 'umask 077 && cat > /mnt/pgdata/compose.env'
   DEPLOY_HOST=NEW infra/deploy.sh
   ```
   `deploy.sh` (full mode, from the PR branch) rewrites `.env` keeping that password, brings up the stack with the 16 GB settings on an empty database, and installs the backup timer and the prewarm unit. Its health checks follow DNS, so they still test the old host.
4. **Certificates.** The new Caddy can't get certificates while DNS points at the old host, and its failed attempts back off. Give it the old host's (they hold private keys: host to host, never printed):
   ```bash
   ssh NEW 'cd /opt/patristica/compose && docker compose stop caddy'
   ssh OLD 'docker run --rm -v patristica_caddy_data:/data alpine tar c -C /data .' \
     | ssh NEW 'docker run --rm -i -v patristica_caddy_data:/data alpine tar x -C /data'
   ssh NEW 'cd /opt/patristica/compose && docker compose start caddy'
   ```
   Without this step, keep Caddy stopped on the new host until step 8; it gets its certificates once DNS points at it.
5. **Freeze and dump.** From here until step 11, no `build_index` or pipeline run: the new database wouldn't have it. Take a fresh dump, `ssh OLD systemctl start patristica-backup.service`, and note its name (`journalctl -u patristica-backup` on OLD prints it). Optionally snapshot the old volume.
6. **Restore into the new host.** On NEW, into the empty `patristica` database:
   ```bash
   cd /opt/patristica/compose && set -a && . ./.env && set +a
   rclone cat spaces:$BACKUP_BUCKET/pg-backups/<name>.dump \
     | docker compose exec -T \
         -e PGOPTIONS='-c maintenance_work_mem=8GB -c max_parallel_maintenance_workers=1' \
         db pg_restore -U patristica -d patristica --no-owner --clean --if-exists
   docker compose exec -T db vacuumdb -U patristica -d patristica --analyze-only
   postgres/prewarm.sh
   ```
   `--clean --if-exists` replaces the extensions initdb created; `pg_restore` must end without "errors ignored on restore". Most of the time is the HNSW index build (~4M vectors, 5.2 GB: it fits in the 8 GB `maintenance_work_mem`, so it is built in memory), plus copying ~8 GB of tables and building the other indexes on the network volume. It hasn't been measured on this hardware: budget 1–3 hours, and note the real time here. Use 3 maintenance workers on a 4-vCPU size. The old host serves meanwhile.
7. **Verify through the new IP**, before users reach it:
   ```bash
   curl --resolve api.patristica.app:443:NEW https://api.patristica.app/healthz
   curl --resolve patristica.app:443:NEW 'https://patristica.app/api/search?q=logos'
   curl --resolve patristica.app:443:NEW -o /dev/null -w '%{http_code}\n' https://patristica.app/
   DEPLOY_HOST=NEW infra/db-tunnel.sh uv run python -m scripts.status --db   # index_meta intact, nothing to load
   ```
   Compare a few row counts with the old host (`DEPLOY_HOST=OLD infra/db-tunnel.sh psql -c 'SELECT count(*) FROM chunk_vectors'`, then with NEW). On NEW, the step-6 prewarm lists the indexes and `free -g` shows them in `buff/cache`; time a cold and a warm search (`docker compose logs api | grep search:`).
8. **Switch DNS.** At Cloudflare, point the A records `patristica.app`, `www.patristica.app` and `api.patristica.app` to NEW (still DNS only). Clients move within the TTL; the old host answers the rest with the same frozen data. Without step 4, start Caddy on NEW now and watch it get its certificates (`docker compose logs -f caddy`).
9. **Point tofu and the Deploy workflow at it.** Set `serving_region` to the new region in `tofu/variables.tf` (commit to the PR) and run `infra/tofu.sh apply` (outputs only, no resource changes). Update the repo secrets: `infra/tofu.sh output -raw ip | gh secret set DEPLOY_HOST` and `ssh-keyscan -t ed25519 NEW | gh secret set DEPLOY_KNOWN_HOSTS` (check the key; see "Deploy workflow").
10. **Stop the old host's backups.** `ssh OLD systemctl disable --now patristica-backup.timer`, so it stops uploading dumps of the frozen database. Leave its stack running until DNS has moved.
11. **Merge the held PR.** Its automatic deploy now goes to the new host, which already runs the same settings. Merge right after step 9: until then, any other merge that deploys would put `master`'s 8 GB settings on the new host. The freeze ends; on the next pipeline run, compare `build_index`'s vectors/s with the old ~12. Set the Cloudflare TTL back to Auto.
12. **Retire the old host after a few days.** `ssh OLD 'cd /opt/patristica/compose && docker compose down'`. Then, in a PR, set `keep_old_host = false` and lift `prevent_destroy` on `digitalocean_volume.pgdata` for that one apply; check that `infra/tofu.sh plan` destroys only the `nyc3` droplet, volume, reserved IP and assignment (and updates the firewall and project) before applying, and put `prevent_destroy` back in the same PR. Delete any manual snapshot.

**Rollback:** until step 8 nothing has changed for users; remove the new host when convenient. After the switch, point the three A records back to OLD, and `DEPLOY_HOST`, `DEPLOY_KNOWN_HOSTS` and `serving_region` with them, and re-enable the backup timer on OLD. The old database holds the step-5 state, so this is safe as long as nothing was loaded on the new host since.

Later size changes within a region are ordinary: change `droplet_size` and apply. A size with a smaller root disk than the current one can't be reached by a resize (DigitalOcean can't shrink a disk); that needs a `-replace` (see "Changing the host") or another move like this one.

## Changing the host

- `cloud-init.yaml` and the base image only apply when the droplet is created, so changing them doesn't replace the droplet. To move the host to another region, see "Moving the host". To rebuild on purpose, run `infra/tofu.sh apply -replace='digitalocean_droplet.db["<region>"]'`, then `infra/deploy.sh`. The data volume (with the database and the host `.env`, `/mnt/pgdata/compose.env`) and the reserved IP survive. The host key changes, so remove the old entry from `~/.ssh/known_hosts` first: `ssh-keygen -R <ip>`.
- The volume and the backups bucket have `prevent_destroy`, so `tofu destroy` stops at them. To tear everything down, remove that line on purpose first.
- The API hostname is `api.patristica.app` (`api_domain`). The domain is registered at Cloudflare and its DNS is managed by hand there: an A record to the reserved IP, **DNS only** (not proxied), so Caddy can get its Let's Encrypt certificate. To change it, update the record, set `api_domain`, then run `infra/tofu.sh apply` and `infra/deploy.sh`. An empty `api_domain` falls back to `<ip-with-dashes>.sslip.io`.
- The web app's hostnames are the apex `patristica.app` and `www.patristica.app`: two more A records to the reserved IP, also **DNS only**. To use another name, run `WEB_DOMAIN=<name> infra/deploy.sh` (and change `WEB_DOMAIN` in the Deploy workflow, which uses it for its health checks). Proxying them through Cloudflare later would need SSL mode *Full (strict)* and a certificate that works behind the proxy (a DNS-01 challenge or a Cloudflare Origin CA certificate); see #132.
