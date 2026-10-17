# Infrastructure

Production database host for Phase 2 (#117): one DigitalOcean droplet running Postgres 16 with pgvector, the FastAPI app (`api/`) and Caddy for TLS, plus nightly database dumps to DigitalOcean Spaces. It also holds the public Spaces bucket and CDN that serve the static library to the web app (#131). Everything is code. The only manual steps are creating the DigitalOcean account and token and generating the SSH key.

| Piece | Where | What it does |
|---|---|---|
| `tofu/` | OpenTofu | Creates the droplet (`s-4vcpu-8gb`, `nyc3`), a 40 GB volume for the Postgres data, a reserved IP, a firewall, the backups bucket and its access key, the library bucket with its CORS rule, CDN and upload key, and a project. State lives in the Spaces bucket `patristica-tfstate`. |
| `tofu/cloud-init.yaml` | first boot | Installs Docker, rclone and unattended-upgrades. Adds 4 GB of swap, turns off SSH passwords and mounts the volume at `/mnt/pgdata`. It contains no secrets. |
| `compose/` | the droplet | Runs `db` (pgvector/pgvector), `api` (built from `api/Dockerfile`) and `caddy` (ports 80/443, Let's Encrypt). Postgres has no published port. |
| `deploy.sh` | your machine | Syncs `compose/` and the API source to `/opt/patristica`, writes the host's `.env`, installs the backup timer and runs `docker compose up`. Idempotent. |
| `tofu.sh` | your machine | Runs `tofu` with the credentials from `infra/.env`. |

Prerequisites on your machine: `tofu` 1.13 ([OpenTofu](https://opentofu.org/docs/intro/install/)), `uv`, `ssh`, `rsync`, `curl`.

## First-time setup

1. **DigitalOcean**: create an account and a personal access token. Use full access, or custom scopes: `droplet`, `block_storage`, `firewall`, `reserved_ip`, `ssh_key` and `spaces_key` (create/read/update/delete each), `project` (the same plus `assign_resource`), `block_storage_action:create` and `block_storage_action:read`, and `regions:read`, `sizes:read`, `image:read`, `actions:read`. Spaces buckets don't use the token; they use the Spaces keys. A missing scope shows up as a 403 naming it on the first `tofu plan`, and you can edit a token's scopes in place. Then:
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
4. **Provision**: running `apply` starts billing (~$48/mo droplet + ~$4 volume + $5 Spaces).
   ```bash
   infra/tofu.sh init
   infra/tofu.sh plan
   infra/tofu.sh apply
   ```
5. **Deploy**: when it finishes, it prints the `/healthz` response from `https://api.patristica.app` (add the DNS record first; see "Changing the host").
   ```bash
   infra/deploy.sh
   ```

## Day to day

- **Deploy changes** to `compose/` or the API: run `infra/deploy.sh`.
- **Shell**: `$(infra/tofu.sh output -raw ssh_command)`, then run `cd /opt/patristica/compose && docker compose ps` / `logs`.
- **psql**: `ssh -i ~/.ssh/patristica_deploy root@<ip> 'cd /opt/patristica/compose && docker compose exec db psql -U patristica'`.
  - For a local client, publish nothing. Tunnel to the container instead: find its address with `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' patristica-db-1`, then `ssh -L 5432:<that ip>:5432 …`.
  - The password is `POSTGRES_PASSWORD` in `/opt/patristica/compose/.env` (a symlink to `/mnt/pgdata/compose.env`). It is generated on the droplet the first time and never leaves it.
- **Run the stack locally** over plain HTTP:
  ```bash
  cd infra/compose && cp .env.local.example .env && docker compose up -d --build --wait
  curl http://localhost:18080/healthz
  ```

## Library

The static library export (`scripts.export_library`) is served from the Spaces bucket `patristica-library` through its CDN, https://patristica-library.nyc3.cdn.digitaloceanspaces.com. The web app's `NEXT_PUBLIC_LIBRARY_URL` is that URL (`infra/tofu.sh output -raw library_url`).

- The bucket listing is private. `scripts.upload_library` uploads each file gzipped and public-read, and keeps its change manifest `_manifest.json` private. The CORS rule (GET/HEAD from any origin) is part of the tofu config.
- The CDN caches each file for `library_cdn_ttl` seconds (600), so `index.json` can be up to 10 minutes stale after a publish.
- The *Publish library* workflow uploads with a Spaces key that can only touch this bucket. Store it as repo secrets once after the first `apply`, without printing it:
  ```bash
  infra/tofu.sh output -raw library_access_key | gh secret set LIBRARY_ACCESS_KEY_ID
  infra/tofu.sh output -raw library_secret_key | gh secret set LIBRARY_SECRET_ACCESS_KEY
  ```
- To publish by hand, put the same two values plus `LIBRARY_BUCKET=patristica-library` in `web/.env` and run `uv run --extra deploy python -m scripts.upload_library` (`--dry-run` first).
- The bucket has no `prevent_destroy`: everything in it is rebuilt from `data/normalized` by one publish run.

## Backups

`patristica-backup.timer` runs `compose/backup/pg-backup.sh` every night at 03:30 UTC. It streams a `pg_dump --format=custom` to `spaces:patristica-backups/pg-backups/` under a timestamped name. The bucket's lifecycle rule deletes dumps after 15 days (`backup_keep_days`). The droplet's Spaces key can only touch that bucket.

- Run one now: `systemctl start patristica-backup && journalctl -u patristica-backup`.
- List them: `cd /opt/patristica/compose && set -a && . ./.env && rclone lsl spaces:$BACKUP_BUCKET/pg-backups/`.
- Restore one, on the droplet: copy the dump into a scratch database first, never straight over production:
  ```bash
  cd /opt/patristica/compose && set -a && . ./.env && set +a
  docker compose exec -T db createdb -U patristica restore_test
  rclone cat spaces:$BACKUP_BUCKET/pg-backups/<name>.dump \
    | docker compose exec -T db pg_restore -U patristica -d restore_test --no-owner
  ```

The full Voyage vectors are archived separately by the index build (`scripts/build_index.py`, Phase 2), so a rebuild doesn't need to re-embed anything.

## Postgres sizing

`compose/postgres/postgresql.conf` is tuned for 8 GB of RAM with a ~5–5.5 GB HNSW index (512-dim `halfvec`, ~4.0M vectors):
- `shared_buffers=2GB`, with the OS page cache holding the rest of the index (`effective_cache_size=6GB`)
- `pg_prewarm` reloads the buffers after a restart

For the index build, raise memory in that session only: `SET maintenance_work_mem = '4GB'; SET max_parallel_maintenance_workers = 3;`.

If searches slow down because the index no longer stays cached (watch disk reads in DigitalOcean monitoring), resize: set `droplet_size = "s-8vcpu-16gb"`, run `infra/tofu.sh apply` (the droplet reboots, and the volume and IP stay), then double the memory settings in `postgresql.conf` and run `infra/deploy.sh`.

## Changing the host

- `cloud-init.yaml` and the base image only apply when the droplet is created, so changing them doesn't replace the droplet. To rebuild on purpose, run `infra/tofu.sh apply -replace=digitalocean_droplet.db`, then `infra/deploy.sh`. The data volume (with the database and the host `.env`, `/mnt/pgdata/compose.env`) and the reserved IP survive. The host key changes, so remove the old entry from `~/.ssh/known_hosts` first: `ssh-keygen -R <ip>`.
- The volume and the backups bucket have `prevent_destroy`, so `tofu destroy` stops at them. To tear everything down, remove that line on purpose first.
- The API hostname is `api.patristica.app` (`api_domain`). The domain is registered at Cloudflare and its DNS is managed by hand there: an A record to the reserved IP, **DNS only** (not proxied), so Caddy can get its Let's Encrypt certificate. To change it, update the record, set `api_domain`, then run `infra/tofu.sh apply` and `infra/deploy.sh`. An empty `api_domain` falls back to `<ip-with-dashes>.sslip.io`.
