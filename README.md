
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

The backend uses a multi-stage Dockerfile (`backend/Dockerfile`) optimized for production environments:
- **Multi-Stage Build**: Separates dependency installation (`builder` using `uv`) from the lightweight runtime image (`final` based on `python:3.12-slim`).
- **Security Hardening**: Executes under non-root user `appuser` (UID 1000) and completely excludes `uv`, `gcc`, and build tools from the final image.
- **Image Optimization**: Reduces container disk size from 488 MB (single-stage) down to 299 MB (-38.7%), with compressed size reduced by ~50% (~69.6 MB).
- Detailed documentation, build commands, and benchmarks are available in [backend/README.md](backend/README.md).
