# Production database host (#117): a droplet running the Docker Compose
# stack in infra/compose (Postgres 16 + pgvector, FastAPI, Next.js, Caddy for
# TLS), plus the Spaces bucket its nightly backups go to, and the public
# Spaces bucket + CDN that serve the static library to the web app (#131).
# Postgres data lives on a separate block-storage volume, so the droplet can
# be resized or replaced without touching the database.
#
# Hosts are keyed by region (local.hosts): the one in var.droplet_region, plus
# the original nyc3 host while var.keep_old_host is set, so the two run side
# by side during the blue-green move of #252 (infra/README.md -> "Moving the
# host"). Each has its own droplet, volume and reserved IP; the Spaces buckets
# stay in var.region. var.serving_region picks the host the outputs (ip,
# ssh_command) name, i.e. the one DNS points at.

locals {
  hosts = merge(
    var.keep_old_host ? {
      # The original host, with its original resource names (renaming the
      # volume would replace it).
      nyc3 = {
        size         = "s-4vcpu-8gb"
        droplet_name = "${var.name}-db"
        volume_name  = "${var.name}-pgdata"
      }
    } : {},
    {
      (var.droplet_region) = {
        size         = var.droplet_size
        droplet_name = "${var.name}-db-${var.droplet_region}"
        volume_name  = "${var.name}-pgdata-${var.droplet_region}"
      }
    },
  )
  serving_ip = digitalocean_reserved_ip.api[var.serving_region].ip_address
  api_domain = var.api_domain != "" ? var.api_domain : "${replace(local.serving_ip, ".", "-")}.sslip.io"
}

# The single-host resources of #117 became the nyc3 entries.
moved {
  from = digitalocean_volume.pgdata
  to   = digitalocean_volume.pgdata["nyc3"]
}

moved {
  from = digitalocean_droplet.db
  to   = digitalocean_droplet.db["nyc3"]
}

moved {
  from = digitalocean_reserved_ip.api
  to   = digitalocean_reserved_ip.api["nyc3"]
}

moved {
  from = digitalocean_reserved_ip_assignment.api
  to   = digitalocean_reserved_ip_assignment.api["nyc3"]
}

resource "digitalocean_ssh_key" "deploy" {
  name       = "${var.name}-deploy"
  public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
}

resource "digitalocean_volume" "pgdata" {
  for_each                = local.hosts
  name                    = each.value.volume_name
  region                  = each.key
  size                    = var.volume_size_gb
  initial_filesystem_type = "ext4"
  description             = "Postgres data directory for ${var.name}"

  lifecycle {
    # Removing a host (keep_old_host = false) needs this lifted on purpose.
    prevent_destroy = true
  }
}

resource "digitalocean_droplet" "db" {
  for_each   = local.hosts
  name       = each.value.droplet_name
  region     = each.key
  size       = each.value.size
  image      = var.droplet_image
  ssh_keys   = [digitalocean_ssh_key.deploy.fingerprint]
  monitoring = true
  ipv6       = true
  # Attached at creation, so the volume is there when cloud-init mounts it.
  volume_ids = [digitalocean_volume.pgdata[each.key].id]

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    volume_device = "/dev/disk/by-id/scsi-0DO_Volume_${each.value.volume_name}"
  })

  lifecycle {
    # cloud-init only runs at first boot, and a new image would rebuild the
    # host. Apply either on purpose: tofu.sh apply -replace='digitalocean_droplet.db["<region>"]'
    ignore_changes = [user_data, image]

    precondition {
      condition     = !(var.keep_old_host && var.droplet_region == "nyc3")
      error_message = "droplet_region is nyc3, the old host's region: set keep_old_host = false, or pick another region."
    }
    precondition {
      condition     = contains(keys(local.hosts), var.serving_region)
      error_message = "serving_region must be droplet_region, or nyc3 while keep_old_host is set."
    }
  }
}

resource "digitalocean_reserved_ip" "api" {
  for_each = local.hosts
  region   = each.key
}

resource "digitalocean_reserved_ip_assignment" "api" {
  for_each   = local.hosts
  ip_address = digitalocean_reserved_ip.api[each.key].ip_address
  droplet_id = digitalocean_droplet.db[each.key].id
}

# Postgres has no published port; only SSH and the Caddy front end are open.
resource "digitalocean_firewall" "db" {
  name        = "${var.name}-db"
  droplet_ids = [for d in digitalocean_droplet.db : d.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = var.ssh_allowed_cidrs
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "80"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "tcp"
    port_range       = "443"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "icmp"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}

# Nightly database dumps (infra/compose/backup). Spaces expires old ones.
resource "digitalocean_spaces_bucket" "backups" {
  name   = var.backups_bucket
  region = var.region
  acl    = "private"

  lifecycle_rule {
    id      = "expire-dumps"
    enabled = true
    prefix  = "pg-backups/"
    expiration {
      days = var.backup_keep_days
    }
    abort_incomplete_multipart_upload_days = 1
  }

  lifecycle {
    prevent_destroy = true
  }
}

# The droplet's key can only touch the backups bucket.
resource "digitalocean_spaces_key" "backups" {
  name = "${var.name}-backups"
  grant {
    bucket     = digitalocean_spaces_bucket.backups.name
    permission = "readwrite"
  }
}

# The static library export (scripts/upload_library.py). The bucket itself is
# private, so its listing isn't public; upload_library makes each work file
# and index.json public-read and keeps its own _manifest.json private.
resource "digitalocean_spaces_bucket" "library" {
  name   = var.library_bucket
  region = var.region
  acl    = "private"
}

# The web app fetches the library from the browser, on any origin.
resource "digitalocean_spaces_bucket_cors_configuration" "library" {
  bucket = digitalocean_spaces_bucket.library.name
  region = var.region

  cors_rule {
    allowed_origins = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_headers = ["*"]
    max_age_seconds = 86400
  }
}

# The web app reads the library through the CDN endpoint (output library_url).
resource "digitalocean_cdn" "library" {
  origin = digitalocean_spaces_bucket.library.bucket_domain_name
  ttl    = var.library_cdn_ttl
}

# The publish workflow's key (GitHub secrets LIBRARY_*) can only touch the library.
resource "digitalocean_spaces_key" "library" {
  name = "${var.name}-library-upload"
  grant {
    bucket     = digitalocean_spaces_bucket.library.name
    permission = "readwrite"
  }
}

resource "digitalocean_project" "patristica" {
  name        = var.name
  description = "Patristica production database, API and library (#117, #131)"
  purpose     = "Web Application"
  environment = "Production"
  resources = concat(
    [for d in digitalocean_droplet.db : d.urn],
    [for v in digitalocean_volume.pgdata : v.urn],
    [for ip in digitalocean_reserved_ip.api : ip.urn],
    [
      digitalocean_spaces_bucket.backups.urn,
      digitalocean_spaces_bucket.library.urn,
    ],
  )
}
