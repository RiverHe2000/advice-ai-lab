variable "project_id" {
  description = "GCP project that hosts the service."
  type        = string
}

variable "region" {
  description = "Region for Artifact Registry and Cloud Run (Sydney keeps client data onshore)."
  type        = string
  default     = "australia-southeast1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "file-note-copilot"
}

variable "repository_id" {
  description = "Artifact Registry repository id."
  type        = string
  default     = "advice-ai-lab"
}

variable "image_tag" {
  description = "Image tag to deploy from the repository (the deploy workflow overrides it per commit)."
  type        = string
  default     = "latest"
}

variable "min_instances" {
  description = "Minimum instances (0 = scale to zero)."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum instances."
  type        = number
  default     = 3
}

variable "cpu" {
  description = "vCPU per instance."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Memory per instance."
  type        = string
  default     = "1Gi"
}

variable "model_kind" {
  description = "Model backend: fake (demo), openai (any OpenAI-compatible endpoint) or hf."
  type        = string
  default     = "fake"

  validation {
    condition     = contains(["fake", "openai", "hf"], var.model_kind)
    error_message = "model_kind must be fake, openai or hf."
  }
}

variable "model_base_url" {
  description = "OpenAI-compatible endpoint (vLLM on GKE/GCE, Vertex AI's OpenAI-compatible API, a gateway)."
  type        = string
  default     = "http://localhost:8000/v1"
}

variable "model_name" {
  description = "Model name sent to the endpoint."
  type        = string
  default     = "Qwen/Qwen2.5-1.5B-Instruct"
}

variable "model_api_key" {
  description = "API key for the model endpoint; stored in Secret Manager, never in the service spec."
  type        = string
  default     = "not-needed"
  sensitive   = true
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to deploy through Workload Identity Federation."
  type        = string
  default     = "RiverHe2000/advice-ai-lab"
}

variable "allow_unauthenticated" {
  description = "Expose the service publicly. Keep false for anything with client data; front it with IAP or a VPN."
  type        = bool
  default     = false
}

variable "extra_env" {
  description = "Additional FILENOTE_* environment variables."
  type        = map(string)
  default     = {}
}
