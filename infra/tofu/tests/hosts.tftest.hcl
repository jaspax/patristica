# Host layout of the #252 blue-green move, planned against a mock provider
# (no DigitalOcean API calls): `tofu -chdir=infra/tofu test` (CI's infra job).
# key.pub is a dummy public key for digitalocean_ssh_key.

mock_provider "digitalocean" {
  mock_resource "digitalocean_droplet" {
    defaults = {
      id = "12345"
    }
  }
  mock_resource "digitalocean_reserved_ip" {
    defaults = {
      ip_address = "192.0.2.1"
    }
  }
}

override_resource {
  target = digitalocean_reserved_ip.api["sfo2"]
  values = {
    ip_address = "192.0.2.2"
  }
}

variables {
  ssh_public_key_path = "tests/key.pub"
}

run "both_hosts" {
  command = plan
  assert {
    condition     = length(digitalocean_droplet.db) == 2 && digitalocean_droplet.db["nyc3"].name == "patristica-db" && digitalocean_volume.pgdata["nyc3"].name == "patristica-pgdata" && digitalocean_droplet.db["sfo2"].size == "m-2vcpu-16gb" && digitalocean_volume.pgdata["sfo2"].region == "sfo2"
    error_message = "hosts wrong"
  }
  assert {
    condition     = digitalocean_spaces_bucket.backups.region == "nyc3"
    error_message = "buckets wrong"
  }
}

run "switched" {
  command = plan
  variables {
    serving_region = "sfo2"
  }
  assert {
    condition     = output.ip == "192.0.2.2" && output.new_host_ip == "192.0.2.2" && output.host_ips["nyc3"] == "192.0.2.1" && length(output.host_ips) == 2
    error_message = "outputs wrong"
  }
}

run "old_removed" {
  command = plan
  variables {
    keep_old_host  = false
    serving_region = "nyc1"
    droplet_region = "nyc1"
    droplet_size   = "s-4vcpu-16gb-320gb-intel"
  }
  assert {
    condition     = keys(digitalocean_droplet.db) == ["nyc1"]
    error_message = "removal wrong"
  }
}
