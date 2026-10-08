from fastapi import FastAPI

from app.routers import admin_state_mapping, health

app = FastAPI(title="CargaExpress Supply Chain API", version="0.1.0")

app.include_router(health.router)
app.include_router(admin_state_mapping.router)
