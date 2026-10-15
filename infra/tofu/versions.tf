terraform {
  required_version = ">= 1.10"

  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.102.0"
    }
  }

  # State lives in the private R2 infra bucket. The bucket and the R2 endpoint
  # are account-specific, so infra/tofu.sh passes them with -backend-config at
  # init time; credentials come from AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
  backend "s3" {
    key    = "tfstate/patristica.tfstate"
    region = "auto"

    use_lockfile                = true
    use_path_style              = true
    skip_credentials_validation = true
    skip_region_validation      = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_s3_checksum            = true
  }
}

# Reads DIGITALOCEAN_TOKEN from the environment.
provider "digitalocean" {}
