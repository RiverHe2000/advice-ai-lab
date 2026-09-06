# Google Cloud Run deployment for file-note-copilot:
#   Artifact Registry repository → Cloud Run v2 service (scale to zero, secret-backed model key)
#   least-privilege runtime service account → Workload Identity Federation for GitHub Actions
#   (no static keys anywhere).

locals {
  services = [
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ]
  image = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}/${var.service_name}:${var.image_tag}"
  env = merge({
    FILENOTE_MODEL__KIND     = var.model_kind
    FILENOTE_MODEL__BASE_URL = var.model_base_url
    FILENOTE_MODEL__MODEL    = var.model_name
    FILENOTE_DRAFT__STRATEGY = "verified"
    FILENOTE_PSEUDONYMISE    = "true"
    FILENOTE_DB_PATH         = "/tmp/drafts.sqlite"
    FILENOTE_AUDIT_PATH      = "/tmp/audit.jsonl"
  }, var.extra_env)
}

resource "google_project_service" "apis" {
  for_each           = toset(local.services)
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ----- images ---------------------------------------------------------------------------------

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  format        = "DOCKER"
  description   = "advice-ai-lab container images"

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  depends_on = [google_project_service.apis]
}

# ----- runtime identity and secret ------------------------------------------------------------

resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${var.service_name}-run"
  display_name = "file-note-copilot runtime (least privilege)"
}

resource "google_secret_manager_secret" "model_key" {
  project   = var.project_id
  secret_id = "${var.service_name}-model-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "model_key" {
  secret      = google_secret_manager_secret.model_key.id
  secret_data = var.model_api_key
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_key" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.model_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# ----- Cloud Run v2 ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "app" {
  project  = var.project_id
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      dynamic "env" {
        for_each = local.env
        content {
          name  = env.key
          value = env.value
        }
      }

      env {
        name = "OPENAI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.model_key.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8080
        }
        initial_delay_seconds = 2
        period_seconds        = 3
        failure_threshold     = 10
      }

      liveness_probe {
        http_get {
          path = "/readyz"
          port = 8080
        }
        period_seconds = 30
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_project_service.apis,
    google_secret_manager_secret_iam_member.runtime_reads_key,
  ]

  lifecycle {
    # the deploy workflow moves the image tag and traffic; Terraform owns the shape
    ignore_changes = [template[0].containers[0].image, traffic, client, client_version]
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ----- Workload Identity Federation for GitHub Actions (no static keys) -----------------------

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Only this repository's workflows can exchange a token.
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "${var.service_name}-deploy"
  display_name = "file-note-copilot deployer (GitHub Actions via WIF)"
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# The deployer may push images, deploy the service and act as the runtime identity — nothing else.
resource "google_artifact_registry_repository_iam_member" "deployer_pushes" {
  project    = var.project_id
  location   = var.region
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_deploys" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}
