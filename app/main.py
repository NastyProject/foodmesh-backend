from fastapi import FastAPI

from app.inventory.router import router as inventory_router

app = FastAPI(title="FoodMesh API", version="0.1.0")
app.include_router(inventory_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}