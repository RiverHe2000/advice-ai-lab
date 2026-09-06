output "service_url" {
  description = "Cloud Run service URL."
  value       = google_cloud_run_v2_service.app.uri
}

output "image" {
  description = "Image reference the service runs (the deploy workflow pushes new tags here)."
  value       = local.image
}

output "artifact_registry" {
  description = "Docker repository host/path for `docker push`."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${var.repository_id}"
}

output "workload_identity_provider" {
  description = "Set as the GitHub variable GCP_WIF_PROVIDER."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account" {
  description = "Set as the GitHub variable GCP_DEPLOYER_SA."
  value       = google_service_account.deployer.email
}

output "runtime_service_account" {
  description = "Identity the service runs as."
  value       = google_service_account.runtime.email
}
