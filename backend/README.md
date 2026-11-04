# CargaExpress Backend Containerization & Multi-Stage Build

This document describes the production Docker architecture, multi-stage build strategy, and image optimization for the CargaExpress Backend service.

---

## 1. Multi-Stage Build Architecture

The backend `Dockerfile` implements a multi-stage build separating dependency resolution and compilation from runtime execution:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Stage 1: builder (python:3.12-slim + uv)                               │
│ - Copies uv binary from ghcr.io/astral-sh/uv:0.11.7                     │
│ - Resolves pyproject.toml & uv.lock with frozen dependencies          │
│ - Installs production packages into isolated virtualenv at /app/.venv  │
│ - Compiles bytecode with UV_COMPILE_BYTECODE=1                         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (copies /app/.venv)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ Stage 3: final (python:3.12-slim runtime)                             │
│ - Base image: python:3.12-slim (minimal footprint)                     │
│ - Creates unprivileged user 'appuser' (UID/GID 1000)                   │
│ - Copies pre-compiled virtualenv (/app/.venv) from builder             │
│ - Copies application source code (backend/app, alembic, scripts)       │
│ - NO uv, gcc, or build toolchains present in final image               │
│ - Runs Alembic migrations + Uvicorn server as appuser                  │
│ - Configured with HEALTHCHECK (/api/v1/ready)                         │
└────────────────────────────────────────────────────────────────────────┘

(Optional Stage 2: 'test' targets full development/test dependencies for running pytest)
```

---

## 2. Security & Hardening Best Practices

- **Non-Root Execution**: Runs under unprivileged user `appuser` (`uid=1000`, `gid=1000`), reducing container breakout risks.
- **Minimal Attack Surface**: The production image does not contain `uv`, `gcc`, build toolchains, or development packages (`pytest`, `mypy`, `ruff`).
- **Context Hygiene**: `.dockerignore` excludes unnecessary files (`.venv`, `__pycache__`, `.pytest_cache`, `.mypy_cache`, tests, logs, `.git`) to ensure fast builds and prevent secret/cache leakage.
- **Deterministic Builds**: Dependency locking via `uv.lock` with `--frozen` flag guarantees reproducible environments.

---

## 3. Build & Verification Commands

### Build the production image:
```bash
docker build -f backend/Dockerfile -t cargaexpress-backend:latest .
```

### Build targeting explicit stages:
```bash
# Production runtime stage
docker build -f backend/Dockerfile --target final -t cargaexpress-backend:final .

# Automated test stage
docker build -f backend/Dockerfile --target test -t cargaexpress-backend:test .
```

### Verify security hardening:
```bash
# 1. Verify unprivileged user:
docker run --rm cargaexpress-backend:latest whoami
# Output: appuser

# 2. Verify UID/GID:
docker run --rm cargaexpress-backend:latest id
# Output: uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)

# 3. Verify absence of uv and build tools:
docker run --rm cargaexpress-backend:latest which uv
# Output: (empty / not found, exit code 1)

docker run --rm cargaexpress-backend:latest which gcc
# Output: (empty / not found, exit code 1)
```

---

## 4. Size Reduction & Performance Benchmark (RIWI-167)

| Metric | Single-Stage Build (with dev/build tools) | Multi-Stage Build (`final` runtime) | Reduction |
| :--- | :--- | :--- | :--- |
| **Uncompressed Disk Size** | **488 MB** | **299 MB** | **-189 MB (-38.7%)** |
| **Compressed Transfer Size** | ~140 MB | ~69.6 MB | **~-70.4 MB (-50.3%)** |
| **Build Tools / Package Managers** | Present (`uv`, dev wheels) | **Removed** (only python3 binary) | 100% eliminated |
| **Execution User** | root (default) | **appuser (UID 1000)** | Hardened |

Compared to a standard non-slim base (`python:3.12` > 1.02 GB), the multi-stage slim design achieves an overall footprint reduction exceeding **70%**.
