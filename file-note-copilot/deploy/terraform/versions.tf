terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # State lives locally by default. For a shared incubator project uncomment and create the
  # bucket first:  gsutil mb -l australia-southeast1 gs://<project>-tfstate
  # backend "gcs" {
  #   bucket = "<project>-tfstate"
  #   prefix = "file-note-copilot"
  # }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
