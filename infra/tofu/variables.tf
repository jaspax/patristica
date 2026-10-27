variable "name" {
  description = "Name prefix for every resource."
  type        = string
  default     = "patristica"
}

variable "region" {
  description = "DigitalOcean region of the Spaces buckets (backups, library; the tfstate bucket too, outside tofu). Stays nyc3 when the droplet moves (#252)."
  type        = string
  default     = "nyc3"
}

# CHOOSE before the #252 apply: the target region and size, whichever the
# DigitalOcean Create screen has in stock (infra/README.md -> "Moving the host"):
#   sfo2 m-2vcpu-16gb (preferred) | nyc1 s-4vcpu-16gb-320gb-intel | atl1 or ric1 g5-2vcpu-16gb-50gb
variable "droplet_region" {
  description = "Region of the database host: its droplet, data volume and reserved IP. CHOOSE (#252); a new value creates a new host next to the others."
  type        = string
  default     = "sfo2"
}

variable "droplet_size" {
  description = "Size slug of the droplet in droplet_region: 16 GB, so the HNSW index stays in the page cache (#252). CHOOSE with droplet_region."
  type        = string
  default     = "m-2vcpu-16gb"
}

variable "keep_old_host" {
  description = "Keep the original nyc3 host (s-4vcpu-8gb, its volume and reserved IP) next to the new one during the blue-green move (#252). Set to false only to remove it, with prevent_destroy lifted on purpose."
  type        = bool
  default     = true
}

variable "serving_region" {
  description = "The host DNS points at: the outputs ip and ssh_command (read by deploy.sh and db-tunnel.sh) name it. nyc3 until the DNS switch of #252, then droplet_region."
  type        = string
  default     = "nyc3"
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
