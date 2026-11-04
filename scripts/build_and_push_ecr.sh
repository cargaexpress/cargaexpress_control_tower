#!/usr/bin/env bash
# ==============================================================================
# CargaExpress Supply Chain Control Tower
# Script: build_and_push_ecr.sh (HU-36 / HU-37)
# Description: Multi-stage Docker build, dual-tagging, and push to Amazon ECR
#              for backend, worker, and airflow images.
# ==============================================================================

set -euo pipefail

# ANSI color codes
CLR_RESET="\033[0m"
CLR_INFO="\033[36m"
CLR_SUCCESS="\033[32m"
CLR_WARN="\033[33m"
CLR_ERR="\033[31m"
CLR_BOLD="\033[1m"

log_info()    { echo -e "${CLR_INFO}[INFO]${CLR_RESET} $1"; }
log_success() { echo -e "${CLR_SUCCESS}[SUCCESS]${CLR_RESET} $1"; }
log_warn()    { echo -e "${CLR_WARN}[WARN]${CLR_RESET} $1"; }
log_error()   { echo -e "${CLR_ERR}[ERROR]${CLR_RESET} $1" >&2; }

# Locate repository root (directory containing this script's parent)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# Default parameters from environment or fallbacks
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-}"
ECR_REGISTRY="${ECR_REGISTRY:-}"
IMAGE_TAG="${IMAGE_TAG:-}"
SERVICES="all"
SKIP_PUSH=false
SKIP_LOGIN=false
CREATE_REPOS=false

show_help() {
  cat << EOF
Usage: $(basename "$0") [OPTIONS]

Compiles and pushes CargaExpress multi-stage container images to Amazon ECR.

Options:
  -r, --region <region>         AWS Region (default: us-east-1, or \$AWS_REGION)
  -a, --account-id <id>         AWS Account ID (default: \$AWS_ACCOUNT_ID or detected via STS)
  --registry <registry>         ECR registry URL (default: <account-id>.dkr.ecr.<region>.amazonaws.com)
  -t, --tag <tag>               Image tag (default: git short SHA or latest)
  -s, --services <svc1,svc2>    Services to build/push: all, backend, worker, airflow (default: all)
  --skip-push                   Build and tag images locally without pushing to ECR
  --skip-login                  Skip 'aws ecr get-login-password' step
  --create-repos                Create ECR repositories if they do not exist
  -h, --help                    Show this help message and exit

Environment Variables:
  AWS_REGION, AWS_ACCOUNT_ID, ECR_REGISTRY, IMAGE_TAG

Examples:
  # Standard build and push with auto-detected account:
  ./scripts/build_and_push_ecr.sh

  # Build specific tag in us-east-2:
  ./scripts/build_and_push_ecr.sh -r us-east-2 -a 123456789012 -t v1.0.0

  # Build backend only without pushing (local test):
  ./scripts/build_and_push_ecr.sh --services backend --skip-push
EOF
}

# Parse CLI arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -r|--region)
      AWS_REGION="$2"
      shift 2
      ;;
    -a|--account-id)
      AWS_ACCOUNT_ID="$2"
      shift 2
      ;;
    --registry)
      ECR_REGISTRY="$2"
      shift 2
      ;;
    -t|--tag)
      IMAGE_TAG="$2"
      shift 2
      ;;
    -s|--services)
      SERVICES="$2"
      shift 2
      ;;
    --skip-push)
      SKIP_PUSH=true
      shift
      ;;
    --skip-login)
      SKIP_LOGIN=true
      shift
      ;;
    --create-repos)
      CREATE_REPOS=true
      shift
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

# Validate prerequisites
log_info "Validating runtime prerequisites..."
if ! command -v docker >/dev/null 2>&1; then
  log_error "Docker CLI is not installed or not available in PATH."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  log_error "Docker daemon is not running or current user lacks permissions."
  exit 1
fi

# Determine AWS Account ID if not provided
if [[ -z "${AWS_ACCOUNT_ID}" ]]; then
  if command -v aws >/dev/null 2>&1; then
    log_info "Detecting AWS Account ID via AWS STS..."
    AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)"
  fi
fi

if [[ -z "${AWS_ACCOUNT_ID}" && "${SKIP_PUSH}" = false ]]; then
  log_error "AWS_ACCOUNT_ID could not be determined. Please supply via -a <id> or set AWS_ACCOUNT_ID."
  exit 1
fi

# Determine ECR registry URL
if [[ -z "${ECR_REGISTRY}" ]]; then
  ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
fi

# Determine Image Tag
if [[ -z "${IMAGE_TAG}" ]]; then
  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    IMAGE_TAG="$(git rev-parse --short HEAD)"
  else
    IMAGE_TAG="latest"
  fi
fi

echo -e "${CLR_BOLD}============================================================${CLR_RESET}"
echo -e "${CLR_BOLD}CargaExpress AWS ECR Build & Push Configuration${CLR_RESET}"
echo -e "  Repository Root: ${REPO_ROOT}"
echo -e "  AWS Region:      ${AWS_REGION}"
echo -e "  AWS Account ID:  ${AWS_ACCOUNT_ID:-N/A (skip-push)}"
echo -e "  ECR Registry:    ${ECR_REGISTRY}"
echo -e "  Image Tag:       ${IMAGE_TAG} (+ latest)"
echo -e "  Target Services: ${SERVICES}"
echo -e "  Push to ECR:     $([ "${SKIP_PUSH}" = true ] && echo "No (skip-push)" || echo "Yes")"
echo -e "${CLR_BOLD}============================================================${CLR_RESET}"

# Function to ensure ECR repository exists
ensure_ecr_repo() {
  local repo_name="$1"
  if [[ "${CREATE_REPOS}" = true ]]; then
    if ! aws ecr describe-repositories --repository-names "${repo_name}" --region "${AWS_REGION}" >/dev/null 2>&1; then
      log_info "Creating missing ECR repository: ${repo_name} in ${AWS_REGION}..."
      aws ecr create-repository \
        --repository-name "${repo_name}" \
        --region "${AWS_REGION}" \
        --image-scanning-configuration scanOnPush=true \
        --encryption-configuration encryptionType=AES256 >/dev/null
      log_success "Repository ${repo_name} created."
    fi
  fi
}

# ECR Login
if [[ "${SKIP_PUSH}" = false && "${SKIP_LOGIN}" = false ]]; then
  log_info "Authenticating Docker with Amazon ECR (${ECR_REGISTRY})..."
  if ! command -v aws >/dev/null 2>&1; then
    log_error "AWS CLI is required for ECR login. Install aws-cli or run with --skip-login if already authenticated."
    exit 1
  fi
  aws ecr get-login-password --region "${AWS_REGION}" | docker login --username AWS --password-stdin "${ECR_REGISTRY}"
  log_success "ECR authentication succeeded."
fi

build_and_tag() {
  local image_name="$1"
  local dockerfile="$2"
  local target_stage="${3:-}"
  local full_tag="${ECR_REGISTRY}/${image_name}:${IMAGE_TAG}"
  local latest_tag="${ECR_REGISTRY}/${image_name}:latest"

  log_info "--> Building container image [${image_name}] from ${dockerfile}..."
  local build_args=("-f" "${dockerfile}" "-t" "${full_tag}" "-t" "${latest_tag}")
  if [[ -n "${target_stage}" ]]; then
    build_args+=("--target" "${target_stage}")
  fi
  build_args+=(".")

  docker build "${build_args[@]}"
  log_success "Image [${image_name}] compiled successfully."

  if [[ "${SKIP_PUSH}" = false ]]; then
    ensure_ecr_repo "${image_name}"
    log_info "--> Pushing [${image_name}:${IMAGE_TAG}] to ECR..."
    docker push "${full_tag}"
    log_info "--> Pushing [${image_name}:latest] to ECR..."
    docker push "${latest_tag}"
    log_success "Image [${image_name}] pushed to ${ECR_REGISTRY} with tags [${IMAGE_TAG}, latest]."
  fi
}

START_TIME=$(date +%s)

# Service 1: cargaexpress-backend
if [[ "${SERVICES}" == "all" || "${SERVICES}" == *"backend"* ]]; then
  build_and_tag "cargaexpress-backend" "backend/Dockerfile" "final"
fi

# Service 2: cargaexpress-worker
if [[ "${SERVICES}" == "all" || "${SERVICES}" == *"worker"* ]]; then
  # The worker shares the backend code base and dependencies but runs app.worker
  # We produce a dedicated image tag to maintain distinct lifecycle and ECR repositories
  build_and_tag "cargaexpress-worker" "backend/Dockerfile" "final"
fi

# Service 3: cargaexpress-airflow
if [[ "${SERVICES}" == "all" || "${SERVICES}" == *"airflow"* ]]; then
  build_and_tag "cargaexpress-airflow" "Dockerfile.airflow" ""
fi

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
log_success "============================================================"
log_success "All requested images processed successfully in ${DURATION}s."
if [[ "${SKIP_PUSH}" = false ]]; then
  log_success "Images deployed to ECR:"
  [[ "${SERVICES}" == "all" || "${SERVICES}" == *"backend"* ]] && echo -e "  - ${ECR_REGISTRY}/cargaexpress-backend:${IMAGE_TAG}"
  [[ "${SERVICES}" == "all" || "${SERVICES}" == *"worker"* ]]  && echo -e "  - ${ECR_REGISTRY}/cargaexpress-worker:${IMAGE_TAG}"
  [[ "${SERVICES}" == "all" || "${SERVICES}" == *"airflow"* ]] && echo -e "  - ${ECR_REGISTRY}/cargaexpress-airflow:${IMAGE_TAG}"
fi
log_success "============================================================"
exit 0
