from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.inventory.router import router as inventory_router
from app.users.router import router as users_router

app = FastAPI(title="FoodMesh API", version="0.1.0")

# El token viaja en el header Authorization (no en cookies), así que no hace
# falta allow_credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory_router)
app.include_router(users_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
