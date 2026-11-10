# Despliegue en EC2 (AWS Academy Learner Lab)

Una EC2 con Docker Compose corre tres contenedores:

```
Internet ──443/80──▶ caddy (HTTPS automático) ──▶ api:8000 ──▶ Amazon RDS (PostgreSQL)
                                                    │  └──────▶ S3 (imágenes de facturas)
                                                    └────────▶ redis (caché de recetas)
```

- **api**: la imagen `ghcr.io/nastyproject/foodmesh-backend`, que publica el CI en cada push a `main`. Al arrancar corre `alembic upgrade head`.
- **redis**: caché de recetas y locks. No guarda nada en disco.
- **caddy**: saca y renueva solo el certificado de Let's Encrypt.

No se usan access keys de AWS: la API toma credenciales temporales del instance profile `LabInstanceProfile`.

## 1. Preparar AWS (una sola vez)

1. **S3**: crea un bucket en `us-east-1`, por ejemplo `foodmesh-facturas-<tu-usuario>`. Déjalo privado, que es lo que viene por defecto.
2. **RDS**: crea una instancia PostgreSQL 16, con base de datos `foodmesh`, sin acceso público.
3. **EC2**: lanza una instancia con Amazon Linux 2023.
   - Tipo t3.small o más grande. Con 1 GB de RAM, dos workers con OpenCV no caben.
   - En *Advanced details → IAM instance profile*, elige `LabInstanceProfile`.
   - Asóciale una **Elastic IP**. Si no, la IP pública cambia cada vez que se reinicia el lab, y con ella el dominio.
4. **Security groups**:
   - EC2: entrada por 22 (solo tu IP), 80 y 443 (desde cualquier origen). Caddy necesita el 80 para validar el certificado.
   - RDS: entrada por 5432 **solo desde el security group de la EC2**.
5. **Dominio**: un registro A que apunte a la Elastic IP. Si no tienes dominio, sirve [sslip.io](https://sslip.io): para la IP `3.80.1.2`, el dominio es `3-80-1-2.sslip.io`.
6. **Metadata (IMDSv2)**: los contenedores llegan a las credenciales del instance profile con un salto de red más que el host, así que el *hop limit* debe ser 2. Amazon Linux 2023 ya viene así. Para revisarlo o cambiarlo desde la consola de AWS CLI del lab:

   ```bash
   aws ec2 modify-instance-metadata-options --instance-id i-XXXX \
       --http-tokens required --http-put-response-hop-limit 2
   ```

   Con hop limit 1, boto3 falla con `NoCredentialsError` al subir una factura.

## 2. Instalar Docker en la EC2 (una sola vez)

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker   # enable: Docker (y los contenedores) arrancan solos al reiniciar
sudo usermod -aG docker ec2-user     # cerrar sesión y volver a entrar para que aplique

# Plugin de Docker Compose (no viene en los repositorios de Amazon Linux)
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
```

## 3. Primer despliegue

```bash
git clone https://github.com/NastyProject/foodmesh-backend.git
cd foodmesh-backend/deploy

cp .env.prod.example .env
chmod 600 .env
nano .env          # DOMINIO, DATABASE_URL, S3_BUCKET, AUTH0_*, GEMINI_API_KEY, CORS_ORIGINS
```

Si el paquete de GHCR es privado, inicia sesión con un token de GitHub (*Settings → Developer settings → Personal access tokens*) que tenga el permiso `read:packages`. Si el paquete es público, sáltate este paso.

```bash
echo "<TOKEN>" | docker login ghcr.io -u <usuario-de-github> --password-stdin
```

Levanta el stack:

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps   # api debe quedar "healthy" (~30 s)
```

Para comprobar que quedó funcionando:

```bash
curl https://<DOMINIO>/health                 # {"status":"ok"}
# En el navegador: https://<DOMINIO>/docs

# ¿La API ve las credenciales del instance profile?
docker compose -f docker-compose.prod.yml exec api \
    python -c "import boto3; print(boto3.client('sts').get_caller_identity()['Arn'])"
```

Tip: con `alias dc='docker compose -f docker-compose.prod.yml'` los comandos quedan más cortos.

## 4. Actualizar a una versión nueva

El CI publica la imagen al hacer merge a `main`. Después, en la EC2:

```bash
cd foodmesh-backend/deploy
git pull                                      # por si cambiaron el compose o el Caddyfile
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d   # recrea solo lo que cambió; las migraciones corren al arrancar
docker image prune -f                         # borra las imágenes viejas (el disco de la EC2 es pequeño)
```

Para **volver a una versión anterior**, pon `API_TAG=<sha del commit>` en `.env` y repite `pull` y `up -d`. El CI publica cada imagen también con el sha del commit. Ojo: si la versión nueva traía una migración, volver atrás la imagen no deshace el cambio en la base de datos.

## 5. Logs y diagnóstico

```bash
docker compose -f docker-compose.prod.yml logs -f api          # API (incluye la latencia de Gemini)
docker compose -f docker-compose.prod.yml logs --tail 100 caddy
docker compose -f docker-compose.prod.yml restart api
```

Los logs rotan solos: 3 archivos de 10 MB por contenedor.

| Síntoma | Causa probable |
|---|---|
| Caddy no obtiene el certificado | El puerto 80 está cerrado en el security group, o el DNS no apunta a la IP de la EC2 |
| `api` se reinicia en bucle, con un error de alembic | No llega a RDS: revisa el security group de RDS, `DATABASE_URL` y `sslmode=require` |
| `NoCredentialsError` / `AccessDenied` al subir facturas | El hop limit de IMDS es 1, a la EC2 le falta `LabInstanceProfile`, o `S3_BUCKET` está mal |
| El frontend recibe errores de CORS | `CORS_ORIGINS` no incluye la URL exacta del frontend (con `https://`) |

Al terminar la sesión del Learner Lab, la EC2 se detiene. Cuando vuelve a arrancar, Docker levanta los contenedores solo (`restart: unless-stopped`), sin hacer nada más.
