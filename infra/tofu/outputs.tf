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
