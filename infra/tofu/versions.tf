terraform {
  required_version = ">= 1.10"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.102.0"
    }
  }

  # State lives in a private Spaces bucket created by scripts.bootstrap_infra.
  # infra/tofu.sh passes the bucket name at init time; credentials come from
  # AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (the bootstrap Spaces key).
  # No lock file: one operator, and Spaces' conditional-write support is
  # not documented.
  backend "s3" {
    key       = "patristica.tfstate"
    region    = "us-east-1"
    endpoints = { s3 = "https://nyc3.digitaloceanspaces.com" }

    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}

# Reads DIGITALOCEAN_TOKEN, SPACES_ACCESS_KEY_ID and SPACES_SECRET_ACCESS_KEY
# from the environment.
provider "digitalocean" {}
