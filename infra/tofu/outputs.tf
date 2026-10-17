output "ip" {
  description = "Reserved IP of the database host (stable across droplet rebuilds)."
  value       = digitalocean_reserved_ip.api.ip_address
}

output "api_hostname" {
  description = "Public hostname Caddy serves the API on (and gets a certificate for)."
  value       = local.api_domain
}

output "ssh_command" {
  description = "How to log in."
  value       = "ssh -i ${trimsuffix(pathexpand(var.ssh_public_key_path), ".pub")} root@${digitalocean_reserved_ip.api.ip_address}"
}

output "backups_bucket" {
  description = "Spaces bucket holding the nightly database dumps."
  value       = digitalocean_spaces_bucket.backups.name
}

output "backups_access_key" {
  description = "Spaces key for the backups bucket (read by infra/deploy.sh)."
  value       = digitalocean_spaces_key.backups.access_key
  sensitive   = true
}

output "backups_secret_key" {
  description = "Secret for backups_access_key (read by infra/deploy.sh)."
  value       = digitalocean_spaces_key.backups.secret_key
  sensitive   = true
}

output "library_bucket" {
  description = "Spaces bucket holding the static library (LIBRARY_BUCKET)."
  value       = digitalocean_spaces_bucket.library.name
}

output "library_url" {
  description = "Public CDN URL of the library: the web app's NEXT_PUBLIC_LIBRARY_URL."
  value       = "https://${digitalocean_cdn.library.endpoint}"
}

output "library_access_key" {
  description = "Spaces key for the library bucket (GitHub secret LIBRARY_ACCESS_KEY_ID)."
  value       = digitalocean_spaces_key.library.access_key
  sensitive   = true
}

output "library_secret_key" {
  description = "Secret for library_access_key (GitHub secret LIBRARY_SECRET_ACCESS_KEY)."
  value       = digitalocean_spaces_key.library.secret_key
  sensitive   = true
}
