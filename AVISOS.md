# 📢 Avisos para frontend

¡Qué más! Te dejo aquí lo que necesitas para arrancar con el frontend. El backend ya tiene **login con Auth0**, **inventario** y **facturas con OCR** funcionando, así que ya puedes conectarte a algo real.

> 🆕 **Novedades de esta versión** (si ya venías usando el backend):
> - Ya están los **endpoints de facturas** (sección 5): subir foto → revisar ítems detectados → confirmar.
> - Las **categorías ahora son una lista cerrada** (sección 4). Cualquier otro valor responde `422`.
> - Los ítems del inventario traen **`es_alimento`**, y hay un filtro **`GET /inventario?solo_alimentos=true`**.
> - Después de hacer `git pull`, corre `alembic upgrade head` (hay migraciones nuevas) y vuelve a generar los tipos (sección 6).

---

## 1. Estado del backend

| Funcionalidad | Estado |
|---|---|
| Login con Auth0 (usuario y hogar se crean solos en el primer login) | ✅ Listo |
| Inventario: listar, crear, ver, editar, borrar ítems | ✅ Listo |
| Subir factura + OCR, revisar y confirmar | ✅ Listo |
| Recomendación de recetas | ⏳ Pendiente |
| Demanda agregada (vista supermercado) | ⏳ Pendiente |

Cada usuario pertenece a un **hogar**, y solo ve el inventario de su hogar. El frontend **nunca** envía el `hogar_id`: el backend lo saca del token.

---

## 2. Correr el backend en tu máquina

Necesitas Python 3.12 y Docker.

```bash
git clone https://github.com/NastyProject/foodmesh-backend.git
cd foodmesh-backend

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env               # te paso los valores de Auth0 por privado

docker compose up -d db            # Postgres
alembic upgrade head               # crea las tablas
uvicorn app.main:app --reload      # API en http://localhost:8000
```

Documentación interactiva de todos los endpoints: **http://localhost:8000/docs**

> El CORS ya permite `http://localhost:5173`, que es el puerto por defecto de Vite. Si usas otro puerto, avísame.

---

## 3. Configurar Auth0 (tu parte)

Ya creé la API en Auth0. Tú necesitas crear la **aplicación del frontend**. Te invito al tenant, o lo hacemos juntos en llamada:

1. **Applications → Create Application → Single Page Application**.
2. En Settings, pon `http://localhost:5173` en estos tres campos:
   - Allowed Callback URLs
   - Allowed Logout URLs
   - Allowed Web Origins
3. Copia el **Client ID** (el de la SPA). Ese sí va en el frontend; no es secreto.

Valores que necesitas:

```env
# .env del frontend
VITE_AUTH0_DOMAIN=dev-7d1om2jb1rsusys2.us.auth0.com
VITE_AUTH0_CLIENT_ID=<client id de tu SPA>
VITE_AUTH0_AUDIENCE=https://api.foodmesh
VITE_API_URL=http://localhost:8000
```

⚠️ El **audience** es obligatorio. Sin él, Auth0 te da un token que el backend no acepta (401).

### Ejemplo con `@auth0/auth0-react`

```tsx
// main.tsx
<Auth0Provider
  domain={import.meta.env.VITE_AUTH0_DOMAIN}
  clientId={import.meta.env.VITE_AUTH0_CLIENT_ID}
  authorizationParams={{
    redirect_uri: window.location.origin,
    audience: import.meta.env.VITE_AUTH0_AUDIENCE,
  }}
>
  <App />
</Auth0Provider>
```

```tsx
// Para llamar al backend
const { getAccessTokenSilently } = useAuth0();

const token = await getAccessTokenSilently();
const res = await fetch(`${import.meta.env.VITE_API_URL}/inventario`, {
  headers: { Authorization: `Bearer ${token}` },
});
```

Te recomiendo envolver esto en una función `apiFetch` única, para no repetirlo en cada pantalla.

> 💡 El backend **no recibe el email** del usuario (Auth0 no lo mete en el access token). Para mostrar nombre, foto o email en la UI, usa `user` de `useAuth0()`.

---

## 4. Endpoints disponibles

Todos (menos `/health`) requieren `Authorization: Bearer <token>`.

| Método | Ruta | Qué hace | Respuesta |
|---|---|---|---|
| GET | `/health` | Verifica que la API está viva | `200` |
| GET | `/me` | Usuario actual (lo crea en el primer login) | `200` |
| GET | `/inventario` | Lista los ítems del hogar, ordenados por vencimiento (los que vencen primero arriba). Con `?solo_alimentos=true` omite aseo, cuidado personal y mascotas | `200` |
| POST | `/inventario` | Crea un ítem | `201` |
| GET | `/inventario/{id}` | Un ítem | `200` / `404` |
| PATCH | `/inventario/{id}` | Edita solo los campos que mandes | `200` / `404` |
| DELETE | `/inventario/{id}` | Borra un ítem | `204` / `404` |
| POST | `/facturas` | Sube la foto de una factura y la procesa (OCR + IA) | `201` / `413` / `415` |
| GET | `/facturas` | Lista las facturas del hogar, la más reciente primero | `200` |
| GET | `/facturas/{id}` | Una factura, con sus ítems detectados | `200` / `404` |
| POST | `/facturas/{id}/confirmar` | Pasa al inventario los ítems que revisó el usuario | `201` / `404` / `409` / `422` |

### Formas de los datos

**Crear ítem (`POST /inventario`):**

```json
{
  "nombre": "Leche entera",
  "categoria": "lacteos",
  "cantidad": 2,
  "unidad": "l",
  "fecha_vencimiento": "2026-11-15"
}
```

Solo `nombre` y `cantidad` son obligatorios. `cantidad` debe ser mayor que 0, y `fecha_vencimiento` va en formato `YYYY-MM-DD` o `null`.

**Categorías:** `categoria` es opcional (puede ser `null`), pero si la mandas tiene que ser **exactamente** una de estas. Cualquier otro valor responde `422`. Úsalas como opciones de un `<select>`, no como texto libre:

| Valor | En pantalla | ¿Alimento? |
|---|---|---|
| `lacteos` | Lácteos | ✅ |
| `carnes_pescados` | Carnes y pescados | ✅ |
| `frutas_verduras` | Frutas y verduras | ✅ |
| `granos_cereales` | Granos y cereales | ✅ |
| `enlatados_conservas` | Enlatados y conservas | ✅ |
| `panaderia` | Panadería | ✅ |
| `bebidas` | Bebidas | ✅ |
| `condimentos_especias` | Condimentos y especias | ✅ |
| `frutos_secos` | Frutos secos | ✅ |
| `snacks_dulces` | Snacks y dulces | ✅ |
| `congelados` | Congelados | ✅ |
| `aseo_hogar` | Aseo del hogar | ❌ |
| `cuidado_personal` | Cuidado personal | ❌ |
| `mascotas` | Mascotas | ❌ |
| `otros` | Otros | ✅ |

> Las categorías viejas (`carnes`, `granos`, `aseo`) ya no existen: la migración las renombró. Si las tenías escritas en el front, cámbialas.

**Ítem que devuelve la API:**

```json
{
  "id": 7,
  "nombre": "Leche entera",
  "categoria": "lacteos",
  "cantidad": 2,
  "unidad": "l",
  "fecha_vencimiento": "2026-11-15",
  "es_alimento": true,
  "creado_en": "2026-11-02T07:15:00Z"
}
```

`es_alimento` lo calcula el backend a partir de la categoría (es `false` solo para aseo, cuidado personal y mascotas, y `true` si no hay categoría). No lo mandes al crear ni al editar: se ignora. Si cambias la categoría con `PATCH`, se recalcula solo. Sirve para separar el inventario en "comida" y "otros", y las recetas solo van a usar alimentos.

**`GET /me`:**

```json
{ "id": 1, "email": null, "hogar_id": 2 }
```

### Errores que debes manejar

| Código | Significa | Qué hacer en la UI |
|---|---|---|
| `401` | Sin token o token inválido/vencido | Mandar a login |
| `404` | El ítem no existe (o es de otro hogar) | Mensaje de "no encontrado" |
| `409` | La factura ya fue confirmada | Mensaje "esta factura ya está en tu inventario" y llevar al inventario |
| `413` | La imagen pesa más de 10 MB | Pedir una foto más liviana (o comprimirla en el front antes de subirla) |
| `415` | El archivo no es JPEG, PNG ni WebP, o no es una imagen | Pedir otra foto |
| `422` | Datos inválidos (ej. cantidad negativa, categoría fuera de la lista) | Mostrar el error en el formulario. El detalle viene en `detail` |

---

## 5. Facturas

### El flujo

1. **Subir:** `POST /facturas` con la foto. La respuesta tarda **unos segundos** (OCR + IA corren dentro de la misma petición), así que muestra un "procesando…" y deshabilita el botón para que no la suban dos veces.
2. **Revisar:** la respuesta trae `items_detectados`. Esa es la pantalla de validación: el usuario corrige nombres, cantidades y categorías, borra lo que no quiera, agrega lo que falte y pone fechas de vencimiento.
3. **Confirmar:** `POST /facturas/{id}/confirmar` con la lista final. Los ítems pasan al inventario y la factura queda `confirmada`. Hasta ese momento **nada** entra al inventario.

### Subir (`POST /facturas`)

Es `multipart/form-data` con el archivo en el campo **`archivo`** (JPEG, PNG o WebP, máximo 10 MB):

```ts
const form = new FormData();
form.append("archivo", file); // el File del <input type="file" accept="image/*" capture="environment">

const res = await fetch(`${import.meta.env.VITE_API_URL}/facturas`, {
  method: "POST",
  headers: { Authorization: `Bearer ${token}` }, // ⚠️ NO pongas Content-Type: el navegador lo arma con el boundary
  body: form,
});
```

### Factura que devuelve la API

```json
{
  "id": 12,
  "estado": "pendiente_validacion",
  "supermercado": "D1",
  "fecha_compra": "2026-11-01",
  "total_impreso": 130690,
  "total_calculado": 130690,
  "requiere_revision": false,
  "texto_ocr": "…texto leído de la foto, sin datos personales…",
  "items_detectados": [
    {
      "codigo": "7700304928750",
      "nombre": "Arándanos 125 g",
      "cantidad": 1,
      "unidad": "unidad",
      "precio_unitario": 6500,
      "precio_total": 6500,
      "categoria": "frutas_verduras",
      "origen": "ia",
      "revisar": false,
      "es_alimento": true
    },
    {
      "codigo": "7700304824342",
      "nombre": "Varsol brillante",
      "cantidad": 1,
      "unidad": "unidad",
      "precio_unitario": 7350,
      "precio_total": 7350,
      "categoria": "aseo_hogar",
      "origen": "catalogo",
      "revisar": false,
      "es_alimento": false
    }
  ],
  "error": null,
  "creado_en": "2026-11-02T19:30:00Z"
}
```

**Campos de la factura:**

| Campo | Qué es | Qué hacer en la UI |
|---|---|---|
| `estado` | `pendiente_validacion` (lista para revisar), `confirmada` (ya está en el inventario) o `error` (falló el OCR o la IA) | Con `error`, muestra el mensaje de `error` y deja que el usuario agregue los ítems a mano: **también se puede confirmar** |
| `supermercado`, `fecha_compra` | Detectados en la factura. Pueden venir `null` | Mostrarlos en el encabezado de la pantalla |
| `total_impreso` | El TOTAL que trae la factura. `null` si no se pudo leer | |
| `total_calculado` | Suma de `precio_total` de los ítems detectados | |
| `requiere_revision` | `true` si los dos totales difieren más del 1 %, o si no se pudieron comparar (no se leyó el TOTAL, o falló la IA) | Mostrar un aviso arriba: "El total no coincide (impreso $130.690, detectado $118.000): revisa que no falte ningún producto" |
| `texto_ocr` | Lo que leyó el OCR, ya sin datos personales | Opcional: un "ver texto leído" plegable, útil en la demo |

**Campos de cada ítem detectado:**

| Campo | Qué es | Qué hacer en la UI |
|---|---|---|
| `codigo` | Código de barras (EAN) o PLU. Puede ser `null` | No mostrarlo (o en gris), pero **devolverlo al confirmar** |
| `precio_unitario`, `precio_total` | En pesos, sin decimales. Pueden ser `null`. **Ya no existe el campo `precio`** | Mostrar el `precio_total` del renglón |
| `categoria` | Una de la lista de la sección 4 | Precargar el `<select>` |
| `origen` | `catalogo`: el nombre y la categoría salieron de un producto que algún usuario ya confirmó antes (más confiable). `ia`: los propuso la IA | Opcional: un ícono pequeño para distinguirlos |
| `revisar` | `true` si cantidad × precio unitario no da el precio total: algún número se leyó mal | **Resaltar el renglón** (borde amarillo, ⚠️) |
| `es_alimento` | Calculado de la categoría, como en el inventario | Opcional: agrupar comida / otros |

### Confirmar (`POST /facturas/{id}/confirmar`)

El body es una **lista** de ítems con la misma forma de `POST /inventario`, más el `codigo` opcional:

```json
[
  {
    "nombre": "Arándanos 125 g",
    "categoria": "frutas_verduras",
    "cantidad": 1,
    "unidad": "unidad",
    "fecha_vencimiento": "2026-11-08",
    "codigo": "7700304928750"
  }
]
```

- Devuelve `201` con la lista de ítems creados en el inventario (con la forma de "Ítem que devuelve la API").
- Manda el `codigo` tal como vino en el ítem detectado (o `null` si no tenía). Con él el backend aprende: la próxima vez que alguien compre ese producto, sale con el nombre y la categoría que confirmó el usuario (`origen: "catalogo"`).
- Es **todo o nada**: si un ítem es inválido (`422`), no se crea ninguno y la factura sigue pendiente.
- Confirmar dos veces la misma factura responde `409`.
- No mandes `precio_unitario`, `precio_total`, `origen`, `revisar` ni `es_alimento`: el inventario no los guarda y se ignoran.

---

## 6. Tipos de TypeScript automáticos

No escribas los tipos a mano: se generan desde el backend, y así nunca quedan desincronizados.

```bash
npm i -D openapi-typescript
npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts
```

Vuelve a correrlo cada vez que te avise que cambió algún endpoint. Si quieres, agrégalo como script `"gen:api"` en el `package.json`.

---

## 7. Pantallas para ir arrancando

Lo que ya puedes hacer contra el backend real:

1. **Login / logout** con Auth0.
2. **Inventario**: lista de ítems, resaltando los que vencen en los próximos 3 días. Con un filtro "solo alimentos" (`?solo_alimentos=true`) o pestañas comida / otros.
3. **Crear y editar ítem**: formulario con nombre, categoría (un `<select>` con la lista cerrada), cantidad, unidad y fecha de vencimiento.
4. **Borrar ítem**, con confirmación.
5. **Subir factura**: tomar foto o subir imagen y mostrar un "procesando…" (tarda unos segundos).
6. **Validar factura**: la lista de ítems detectados, editable, con los renglones `revisar: true` resaltados y el aviso de `requiere_revision` arriba. El usuario corrige, agrega fechas de vencimiento y confirma. Es la pantalla más importante de la demo.
7. **Historial de facturas** (`GET /facturas`): supermercado, fecha, total y estado; las pendientes se pueden abrir para terminar de validarlas.

Lo que viene, y que puedes maquetar con datos falsos mientras tanto:

8. **Preferencias**: dieta y alergias.
9. **Recetas sugeridas**: 2–3 tarjetas con ingredientes y pasos, destacando los productos próximos a vencer.
10. **Vista supermercado**: un panel con la demanda agregada por categoría y zona.

---

## 8. Acuerdos de trabajo

- Trabajamos con **ramas + PR** (`feat/login`, `feat/inventario`…). Nada directo a `main`.
- Si necesitas un endpoint o un campo que no existe, me escribes y lo agregamos. No lo resuelvas con lógica rara en el front.
- El **despliegue del frontend** va en Vercel; lo configuramos cuando tengamos las primeras pantallas.
- Al final, tú grabas el **video de la demo**, así que piensa en el flujo desde ya: login → subir factura → validar → inventario → recetas.

Cualquier duda, me escribes. 🚀