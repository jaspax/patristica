# Production database host (#117): one droplet running the Docker Compose
# stack in infra/compose (Postgres 16 + pgvector, FastAPI, Caddy for TLS),
# plus the Spaces bucket its nightly backups go to, and the public Spaces
# bucket + CDN that serve the static library to the web app (#131).
# Postgres data lives on a separate block-storage volume, so the droplet can
# be resized or replaced without touching the database.

locals {
  volume_name = "${var.name}-pgdata"
  api_domain  = var.api_domain != "" ? var.api_domain : "${replace(digitalocean_reserved_ip.api.ip_address, ".", "-")}.sslip.io"
}

resource "digitalocean_ssh_key" "deploy" {
  name       = "${var.name}-deploy"
  public_key = trimspace(file(pathexpand(var.ssh_public_key_path)))
}

resource "digitalocean_volume" "pgdata" {
  name                    = local.volume_name
  region                  = var.region
  size                    = var.volume_size_gb
  initial_filesystem_type = "ext4"
  description             = "Postgres data directory for ${var.name}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_droplet" "db" {
  name       = "${var.name}-db"
  region     = var.region
  size       = var.droplet_size
  image      = var.droplet_image
  ssh_keys   = [digitalocean_ssh_key.deploy.fingerprint]
  monitoring = true
  ipv6       = true
  # Attached at creation, so the volume is there when cloud-init mounts it.
  volume_ids = [digitalocean_volume.pgdata.id]

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    volume_device = "/dev/disk/by-id/scsi-0DO_Volume_${local.volume_name}"
  })

  lifecycle {
    # cloud-init only runs at first boot, and a new image would rebuild the
    # host. Apply either on purpose: tofu.sh apply -replace=digitalocean_droplet.db
    ignore_changes = [user_data, image]
  }
}

resource "digitalocean_reserved_ip" "api" {
  region = var.region
}

resource "digitalocean_reserved_ip_assignment" "api" {
  ip_address = digitalocean_reserved_ip.api.ip_address
  droplet_id = digitalocean_droplet.db.id
}

# Postgres has no published port; only SSH and the Caddy front end are open.
resource "digitalocean_firewall" "db" {
  name        = "${var.name}-db"
  droplet_ids = [digitalocean_droplet.db.id]

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
  resources = [
    digitalocean_droplet.db.urn,
    digitalocean_volume.pgdata.urn,
    digitalocean_reserved_ip.api.urn,
    digitalocean_spaces_bucket.backups.urn,
    digitalocean_spaces_bucket.library.urn,
  ]
}
