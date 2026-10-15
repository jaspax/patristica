# Production database host (#117): one droplet running the Docker Compose
# stack in infra/compose (Postgres 16 + pgvector, FastAPI, Caddy for TLS).
# Postgres data lives on a separate block-storage volume, so the droplet can
# be resized or rebuilt without touching the database.

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

resource "digitalocean_project" "patristica" {
  name        = var.name
  description = "Patristica production database and API (#117)"
  purpose     = "Web Application"
  environment = "Production"
  resources = [
    digitalocean_droplet.db.urn,
    digitalocean_volume.pgdata.urn,
    digitalocean_reserved_ip.api.urn,
  ]
}
