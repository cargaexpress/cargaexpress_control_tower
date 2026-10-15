from fastapi import FastAPI

from app.routers import admin_mapeo_estados, admin_state_mapping, health, orders

# Routers keep health, admin mapping, and order APIs independently organized.
# Registering them here makes their endpoints part of the running application.
# Los routers separan salud, administración de mapeos y API de pedidos.
# Registrarlos aquí publica sus endpoints en la aplicación.
app = FastAPI(title="CargaExpress Supply Chain API", version="0.1.0")

app.include_router(health.router)
app.include_router(admin_state_mapping.router)
app.include_router(admin_mapeo_estados.router)
app.include_router(orders.router)
