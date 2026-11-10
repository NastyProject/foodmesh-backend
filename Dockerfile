FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-spa libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Workers de uvicorn (procesos). Cada uno atiende peticiones en paralelo; en una EC2
# pequeña, 2 es un buen punto de partida (más consume más RAM: cada worker carga
# OpenCV y el SDK de Gemini).
ENV WEB_CONCURRENCY=2
# Detrás de Caddy: uvicorn confía en los headers X-Forwarded-* (protocolo https e IP
# real del cliente) solo si vienen de estas IPs. "*" es seguro porque en producción
# el contenedor no expone puertos: solo Caddy, en la red interna de Docker, le habla.
ENV FORWARDED_ALLOW_IPS="*"

EXPOSE 8000
# exec: uvicorn reemplaza al shell y recibe directamente las señales de Docker (SIGTERM
# al hacer `docker compose down`), así se apaga limpio.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers \"$WEB_CONCURRENCY\" --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\""]
