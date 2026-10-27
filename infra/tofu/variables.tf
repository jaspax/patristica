variable "name" {
  description = "Name prefix for every resource."
  type        = string
  default     = "patristica"
}

variable "region" {
  description = "DigitalOcean region. nyc3 is the closest to Vercel's default function region (iad1)."
  type        = string
  default     = "nyc3"
}

variable "droplet_size" {
  description = "Droplet size slug. Memory-optimized, so the HNSW index stays in the page cache (#252). Changing it from a size with a larger root disk is a replacement, not a resize: DigitalOcean can't shrink a disk (infra/README.md)."
  type        = string
  default     = "m-2vcpu-16gb"
}

variable "droplet_image" {
  description = "Base image. Only read when the droplet is created (see lifecycle in main.tf)."
  type        = string
  default     = "ubuntu-24-04-x64"
}

variable "volume_size_gb" {
  description = "Size of the block-storage volume that holds the Postgres data directory. Can grow, never shrink."
  type        = number
  default     = 40
}

variable "ssh_public_key_path" {
  description = "Public half of the dedicated deploy key (the private key lives in the password manager)."
  type        = string
  default     = "~/.ssh/patristica_deploy.pub"
}

variable "ssh_allowed_cidrs" {
  description = "Source addresses allowed to reach SSH. Password login is disabled, so open by default."
  type        = list(string)
  default     = ["0.0.0.0/0", "::/0"]
}

variable "api_domain" {
  description = "Public hostname of the API (Cloudflare DNS: A record to the reserved IP, DNS only). Empty means <reserved-ip-with-dashes>.sslip.io."
  type        = string
  default     = "api.patristica.app"
}

variable "backups_bucket" {
  description = "Spaces bucket for the nightly pg_dump (bucket names are global per region)."
  type        = string
  default     = "patristica-backups"
}

variable "backup_keep_days" {
  description = "Days a database dump is kept before Spaces expires it."
  type        = number
  default     = 15
}

variable "library_bucket" {
  description = "Public Spaces bucket for the static library export (scripts/upload_library.py)."
  type        = string
  default     = "patristica-library"
}

variable "library_cdn_ttl" {
  description = "Seconds the CDN caches a library file (60, 600, 3600, 86400 or 604800). Bounds how stale index.json is after a publish."
  type        = number
  default     = 600
}
