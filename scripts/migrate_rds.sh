#!/usr/bin/env bash
# ==============================================================================
# CargaExpress Supply Chain Control Tower
# Script: migrate_rds.sh (HU-38)
# Description: Automated database migration executor for Amazon RDS PostgreSQL.
#              Executes Alembic migrations and validates schema consistency.
# ==============================================================================

set -euo pipefail

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

# Locate repository root and backend directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${REPO_ROOT}/backend"

# Default parameters
DB_HOST=""
DB_PORT="5432"
DB_USER="cargaexpress"
DB_PASSWORD=""
DB_NAME="cargaexpress"
DB_SSL_MODE="require"
CUSTOM_DATABASE_URL="${DATABASE_URL:-}"
ACTION="upgrade"
REVISION="head"
VERIFY_SCHEMA=true
SQL_ONLY=false

show_help() {
  cat << EOF
Usage: $(basename "$0") [OPTIONS]

Executes Alembic migrations against AWS RDS PostgreSQL database for CargaExpress.

Connection Options (provide DATABASE_URL or individual connection parameters):
  -u, --database-url <url>      Full connection URL (postgresql+asyncpg://user:pass@host:5432/db)
  -H, --host <host>             RDS host endpoint (e.g. cargaexpress.c123.us-east-1.rds.amazonaws.com)
  -p, --port <port>             PostgreSQL port (default: 5432)
  -U, --user <user>             Database username (default: cargaexpress)
  -P, --password <password>     Database password (or via DB_PASSWORD env var)
  -d, --database <db>           Database name (default: cargaexpress)
  --ssl-mode <mode>             SSL mode: require, prefer, disable (default: require)

Migration Actions:
  -a, --action <action>         Migration action: upgrade (default), check, downgrade, current, heads, history
  -r, --revision <rev>          Target revision for upgrade/downgrade (default: head for upgrade, -1 for downgrade)
  --no-verify                   Skip schema drift verification ('alembic check') after upgrade
  --sql                         Output SQL statements without executing against DB (offline mode)
  -h, --help                    Show this help message and exit

Environment Variables:
  DATABASE_URL, DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSL_MODE

Examples:
  # Migrate using full DATABASE_URL:
  DATABASE_URL="postgresql+asyncpg://appuser:secPass123@rds.host.com:5432/cargaexpress" ./scripts/migrate_rds.sh

  # Migrate using discrete RDS parameters:
  ./scripts/migrate_rds.sh -H rds.internal.amazonaws.com -U dbadmin -P "MyStr0ngPass!" -d cargaexpress

  # Verify schema parity without applying migrations:
  ./scripts/migrate_rds.sh -H rds.internal.amazonaws.com -U dbadmin -P "pass" --action check

  # Generate offline SQL script:
  ./scripts/migrate_rds.sh -H rds.internal.amazonaws.com -U dbadmin -P "pass" --sql > migration.sql
EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -u|--database-url)
      CUSTOM_DATABASE_URL="$2"
      shift 2
      ;;
    -H|--host)
      DB_HOST="$2"
      shift 2
      ;;
    -p|--port)
      DB_PORT="$2"
      shift 2
      ;;
    -U|--user)
      DB_USER="$2"
      shift 2
      ;;
    -P|--password)
      DB_PASSWORD="$2"
      shift 2
      ;;
    -d|--database)
      DB_NAME="$2"
      shift 2
      ;;
    --ssl-mode)
      DB_SSL_MODE="$2"
      shift 2
      ;;
    -a|--action)
      ACTION="$2"
      shift 2
      ;;
    -r|--revision)
      REVISION="$2"
      shift 2
      ;;
    --no-verify)
      VERIFY_SCHEMA=false
      shift
      ;;
    --sql)
      SQL_ONLY=true
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

# Fallback to DB_* environment variables
DB_HOST="${DB_HOST:-${RDS_HOSTNAME:-}}"
DB_PASSWORD="${DB_PASSWORD:-${RDS_PASSWORD:-}}"

# Construct final connection URL
TARGET_URL=""
if [[ -n "${CUSTOM_DATABASE_URL}" ]]; then
  TARGET_URL="${CUSTOM_DATABASE_URL}"
elif [[ -n "${DB_HOST}" && -n "${DB_PASSWORD}" ]]; then
  # Ensure asyncpg driver dialect
  if [[ "${DB_SSL_MODE}" == "disable" ]]; then
    TARGET_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}"
  else
    TARGET_URL="postgresql+asyncpg://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?ssl=${DB_SSL_MODE}"
  fi
else
  log_error "Missing database connection credentials."
  log_error "Provide either --database-url or --host with --password."
  exit 1
fi

# Normalize scheme: SQLAlchemy models require postgresql+asyncpg://
if [[ "${TARGET_URL}" =~ ^postgres:// ]]; then
  TARGET_URL="postgresql+asyncpg://${TARGET_URL#postgres://}"
elif [[ "${TARGET_URL}" =~ ^postgresql:// ]]; then
  TARGET_URL="postgresql+asyncpg://${TARGET_URL#postgresql://}"
fi

# Mask password for display
MASKED_URL="$(echo "${TARGET_URL}" | sed -E 's/:\/\/([^:]+):([^@]+)@/:\/\/\1:****@/')"

log_info "============================================================"
log_info "CargaExpress RDS Database Migration Runner"
log_info "  Action:       ${ACTION} (target: ${REVISION})"
log_info "  Target DB:    ${MASKED_URL}"
log_info "  SQL Only:     ${SQL_ONLY}"
log_info "  Verify Drift: ${VERIFY_SCHEMA}"
log_info "============================================================"

# Navigate to backend directory where alembic.ini lives
cd "${BACKEND_DIR}"

# Export DATABASE_URL for app.config.settings and alembic/env.py
export DATABASE_URL="${TARGET_URL}"

# Determine Alembic execution runner (uv run preferred, fallback to alembic or python -m alembic)
RUNNER=()
if command -v uv >/dev/null 2>&1; then
  RUNNER=("uv" "run" "python" "-m" "alembic")
elif command -v alembic >/dev/null 2>&1; then
  RUNNER=("alembic")
elif command -v python3 >/dev/null 2>&1; then
  RUNNER=("python3" "-m" "alembic")
elif command -v python >/dev/null 2>&1; then
  RUNNER=("python" "-m" "alembic")
else
  log_error "Neither 'uv', 'alembic' nor 'python' was found in PATH."
  exit 1
fi

execute_alembic() {
  "${RUNNER[@]}" "$@"
}

START_TIME=$(date +%s)

case "${ACTION}" in
  upgrade)
    if [[ "${SQL_ONLY}" = true ]]; then
      log_info "Generating offline SQL statements for upgrade to ${REVISION}..."
      execute_alembic upgrade "${REVISION}" --sql
      log_success "Offline SQL generation complete."
      exit 0
    fi

    log_info "Applying pending migrations up to revision [${REVISION}]..."
    execute_alembic upgrade "${REVISION}"
    log_success "Migrations successfully applied."

    if [[ "${VERIFY_SCHEMA}" = true ]]; then
      log_info "Verifying schema consistency and model synchronization (alembic check)..."
      if execute_alembic check; then
        log_success "Schema verification passed. Database is completely synchronized with SQLAlchemy models."
      else
        log_warn "Schema check detected differences between models and database."
      fi
    fi
    ;;

  check)
    log_info "Checking for schema drift or unapplied migrations..."
    execute_alembic check
    log_success "Schema check completed."
    ;;

  downgrade)
    TARGET_REV="${REVISION}"
    if [[ "${TARGET_REV}" == "head" ]]; then
      TARGET_REV="-1"
    fi
    log_warn "Downgrading database schema to [${TARGET_REV}]..."
    execute_alembic downgrade "${TARGET_REV}"
    log_success "Downgrade executed."
    ;;

  current)
    log_info "Querying current database revision..."
    execute_alembic current
    ;;

  heads)
    log_info "Displaying latest available migration heads..."
    execute_alembic heads
    ;;

  history)
    log_info "Displaying migration history..."
    execute_alembic history --verbose
    ;;

  *)
    log_error "Unsupported migration action: ${ACTION}. Choose upgrade, check, downgrade, current, heads, history."
    exit 1
    ;;
esac

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))
log_success "Database operation '${ACTION}' finished successfully in ${DURATION}s."
