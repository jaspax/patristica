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
  description = "Droplet size slug. Resize to s-8vcpu-16gb if the HNSW index does not stay cached (#117)."
  type        = string
  default     = "s-4vcpu-8gb"
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
  description = "Public hostname of the API. Empty means <reserved-ip-with-dashes>.sslip.io."
  type        = string
  default     = ""
}
