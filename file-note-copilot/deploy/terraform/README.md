# Cloud Run deployment (Terraform)

What `terraform apply` creates in one GCP project:

| Resource | Purpose |
|---|---|
| Artifact Registry repository `advice-ai-lab` | container images, keeps the 10 most recent tags |
| Cloud Run v2 service `file-note-copilot` | the app: 1 vCPU / 1 GiB, **min 0** (scale to zero) / max 3 instances, startup probe on `/health`, liveness on `/readyz`, CPU only allocated while serving |
| Secret Manager secret `file-note-copilot-model-api-key` | the model endpoint key, mounted as `OPENAI_API_KEY`; the runtime service account is the only reader |
| Service account `file-note-copilot-run` | runtime identity with exactly one role (secret accessor) |
| Workload Identity Federation pool `github-actions` + OIDC provider | lets `ci/deploy-cloud-run.yml` obtain short-lived credentials; the provider's attribute condition pins the GitHub repository, so no static JSON key ever exists |
| Service account `file-note-copilot-deploy` | what the workflow impersonates: push images, deploy revisions, act as the runtime identity — nothing else |

The model itself is **not** in this stack. The service talks to any OpenAI-compatible endpoint
(`model_base_url`): vLLM on a GPU VM or GKE node pool, Vertex AI's OpenAI-compatible API, or
a gateway such as the owner's `llm-gateway-release`. `model_kind = "fake"` (the default) runs
the scripted backend, which is enough to prove the deployment path.

## Apply

```bash
cd deploy/terraform
terraform init
terraform apply -var project_id=my-incubator-project \
  -var model_kind=openai -var model_base_url=https://vllm.internal/v1 \
  -var model_api_key="$MODEL_KEY" -var github_repository=ChuanHe-PhD/advice-ai-lab
terraform output            # → workload_identity_provider, deployer_service_account, service_url
```

Then set the GitHub repository variables `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WIF_PROVIDER`
and `GCP_DEPLOYER_SA` from the outputs. The deploy workflow is inert until `GCP_PROJECT_ID`
is set. The first `apply` creates the service with the `latest` tag, which does not exist yet:
push one image first (`docker build -f deploy/Dockerfile -t <artifact_registry>/file-note-copilot:latest . && docker push …`),
or run the workflow once after `apply` fails on the missing image and re-apply.

`allow_unauthenticated` defaults to `false`: a service that sees client transcripts belongs
behind Identity-Aware Proxy or a VPC connector, not on the open internet.

## Validate without a project

```bash
docker run --rm -v "$PWD/deploy/terraform:/w" -w /w hashicorp/terraform:1.9 init -backend=false
docker run --rm -v "$PWD/deploy/terraform:/w" -w /w hashicorp/terraform:1.9 validate
docker run --rm -v "$PWD/deploy/terraform:/w" -w /w hashicorp/terraform:1.9 fmt -check -recursive
```

The output of these three commands is committed in `docs/experiments/terraform_validate.txt`.

## Cost

With `min_instances = 0` the service costs nothing while idle. Cloud Run's free tier
(2 million requests, 360 000 vCPU-seconds and 180 000 GiB-seconds a month at the time of
writing) covers an incubator pilot; beyond it, 1 vCPU / 1 GiB is roughly AUD 0.10 per
hour *of actual request time*. Artifact Registry storage is cents per GB-month, Secret
Manager access is negligible at this volume and WIF is free. The GPU model server, if you
run one, is the real cost — which is exactly why it is a separate endpoint the app points at,
not part of this stack.

## Teardown

```bash
terraform destroy -var project_id=my-incubator-project
```

`disable_on_destroy = false` on the APIs keeps other workloads in the project untouched.
Secret versions are destroyed with the secret; images go with the repository.
