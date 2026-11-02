# FoodMesh Backend

API REST de FoodMesh: plataforma multi-tenant para reducir el desperdicio de alimentos.
Prototipo académico (Fase 0): factura → OCR → inventario → recetas con LLM.

## Stack
- Python 3.12, FastAPI, SQLAlchemy 2 (estilo `Mapped`/`mapped_column`), Alembic, PostgreSQL
- Pydantic v2 + pydantic-settings (config en `app/core/config.py`, leída de env vars)
- Auth: Auth0 (el backend solo VALIDA tokens RS256, no los emite)
- Tests: pytest + TestClient; lint: ruff

## Estructura
Monolito modular. Cada módulo en `app/<modulo>/` tiene:
- `models.py` (tablas), `schemas.py` (entrada/salida), `service.py` (lógica y consultas), `router.py` (endpoints)
- El router nunca consulta la BD directamente: delega en el service.

## Convenciones obligatorias
- Multi-tenancy: TODA consulta de datos de hogar filtra por `hogar_id`. Un recurso de otro hogar responde 404, no 403.
- `hogar_id` nunca viene del cliente: sale de la dependencia `HogarId` (`app/auth/dependencies.py`).
- Dependencias con `Annotated` (`DbSession`, `HogarId`), nunca `= Depends(...)` en los parámetros.
- Los schemas de salida no exponen `hogar_id` ni datos internos.
- Nombres de dominio en español (tablas, campos, funciones); código y comentarios claros.
- Secretos solo por variables de entorno; actualizar `.env.example` al agregar una.
- Cada cambio de modelos lleva su migración de Alembic (autogenerate + revisión manual).
- Los tests nunca llaman servicios externos (Auth0, LLM): usar `app.dependency_overrides` o mocks.

## Antes de dar una tarea por terminada
1. `ruff check .`
2. `alembic upgrade head` (con Postgres de `docker compose up -d db`)
3. `pytest`

## Forma de trabajar
- Estoy aprendiendo FastAPI: al terminar, explica brevemente qué hiciste y por qué en cada archivo.
- No hagas commit ni push; yo reviso y subo.
- Si algo es ambiguo, pregunta antes de inventar.