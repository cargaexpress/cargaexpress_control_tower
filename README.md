
# CargaExpress Control Tower

Backend API for the CargaExpress logistics control tower. The project centralizes shipment information and supports warehouse management operations.

## Technologies

- Python
- FastAPI
- SQLAlchemy
- Alembic
- PostgreSQL
- Docker
- Docker Compose

## Requirements

- Git
- Docker Desktop
- Docker Compose v2

## Getting Started

### 1. Clone the Repository

```bash
git clone https://github.com/cargaexpress/cargaexpress_control_tower.git
cd cargaexpress_control_tower
```

### 2. Configure Environment Variables

Create the environment file from the provided template.

On Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Configure the required variables in the `.env` file.

### 3. Start the Application

Run the following command from the project root:

```bash
docker compose up --build
```

Docker Compose starts the backend API and PostgreSQL database.

### 4. Access the Application

- API: http://localhost:8000
- API Documentation: http://localhost:8000/docs
- Health Check: http://localhost:8000/api/v1/health

### 5. Stop the Application

Press `Ctrl + C` to stop the running process.

To stop and remove the containers:

```bash
docker compose down
```

Persistent database data is preserved when using this command.

## Project Structure

```text
cargaexpress_control_tower/
├── backend/
├── .env.example
├── .gitignore
├── docker-compose.yml
└── README.md
```

## Development

The project is under active development. New features, requirements, and technical decisions are documented separately as development progresses.

## Repository

https://github.com/cargaexpress/cargaexpress_control_tower




## Database Visualization

Developers can optionally install a PostgreSQL extension in Visual Studio Code to connect to the database and visualize tables, schemas, and database structures.

Recommended extension: [PostgreSQL by Microsoft](https://marketplace.visualstudio.com/items?itemName=ms-ossdata.vscode-postgresql)

This extension is optional and is intended to make database inspection easier during development.

To connect, use the PostgreSQL connection settings defined in the project's environment variables.

Note: Database migrations are managed through Alembic. To review migration history and schema changes, check the migration files in the project.

## Backend Containerization & Docker Optimization

The backend uses a multi-stage Dockerfile (ackend/Dockerfile) optimized for production environments:
- **Multi-Stage Build**: Separates dependency installation (uilder using uv) from the lightweight runtime image (inal based on python:3.12-slim).
- **Security Hardening**: Executes under non-root user ppuser (UID 1000) and completely excludes uv, gcc, and build tools from the final image.
- **Image Optimization**: Reduces container disk size from 488 MB (single-stage) down to 299 MB (-38.7%), with compressed size reduced by ~50% (~69.6 MB).
- Detailed documentation, build commands, and benchmarks are available in [backend/README.md](backend/README.md).

---

## Docker Image Optimization & Benchmark Report (Entregable E-13 / RIWI-168)

As part of Sprint 3 and User Story HU-35 (RIWI-168), all Docker workloads across the CargaExpress ecosystem (Backend, Airflow, and Simulators A, B, and C) have been refactored to hardened multi-stage builds.

### Ecosystem Benchmark Summary

| Component / Subsystem | Base / Single-Stage | Multi-Stage Optimized | Compressed Transfer Size | Footprint Reduction | Runtime User | Key Optimizations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Backend (Control Tower API)** | python:3.12 (488 MB) | python:3.12-slim | **299 MB** | 69.6 MB | **-38.7%** | ppuser (1000) | Stripped uv & gcc; bytecode compiled; /api/v1/ready healthcheck. |
| **Airflow Orchestrator (Custom)** | Standard setup (~2.3 GB) | apache/airflow:2.9.3 pre-baked | **2.01 GB** | 407 MB | **-290 MB** | irflow (50000) | Alpine PostgreSQL & RabbitMQ; demo DAGs disabled; worker tuning. |
| **Simulator A (Push Webhooks)** | python:3.12 (390 MB) | python:3.12-slim 3-stage | **205 MB** | 49.5 MB | **-47.4%** | pp (10001) | Dedicated SQLite storage volume; isolated test stage. |
| **Simulator B - Carrier A (PostgreSQL)** | python:3.12-slim (485 MB) | python:3.12-slim multi-stage | **305 MB** | 71.0 MB | **-37.1%** | ppuser (1000) | Compiled virtualenv; stripped build tools; automatic migrations. |
| **Simulator B - Carrier B (MySQL)** | python:3.12-slim (460 MB) | python:3.12-slim multi-stage | **278 MB** | 65.2 MB | **-39.5%** | ppuser (1000) | Native PyMySQL driver; pre-compiled wheels. |
| **Simulator B - Carrier C (MongoDB)** | python:3.12-slim (435 MB) | python:3.12-slim multi-stage | **249 MB** | 58.8 MB | **-42.7%** | ppuser (1000) | Lean pymongo runtime; zero relational database overhead. |
| **Simulator B - Carrier D (SQLite)** | python:3.12-slim (455 MB) | python:3.12-slim multi-stage | **277 MB** | 65.1 MB | **-39.1%** | ppuser (1000) | Pre-configured /data directory with UID 1000 ownership. |
| **Simulator B - Tools (Seed / Generator)** | python:3.12-slim (425 MB) | python:3.12-slim multi-stage | **258 MB** | 60.4 MB | **-39.3%** | ppuser (1000) | Batch seed and background generator running as unprivileged user. |
| **Simulator C (Batch Files & WMS Seed)** | python:3.12-slim (430 MB) | python:3.12-slim multi-stage | **257 MB** | 60.7 MB | **-40.2%** | seeduser (1000) | Frozen lockfile; uv binary stripped from final image. |

For detailed operational guides and architecture references:
- **Backend Build Guide**: See [backend/README.md](backend/README.md)
- **Airflow Orchestration & Benchmark Details**: See [AIRFLOW_SETUP.md](AIRFLOW_SETUP.md)
