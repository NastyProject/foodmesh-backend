# 📢 Avisos para frontend

¡Qué más! Te dejo aquí lo que necesitas para arrancar con el frontend. El backend ya tiene **login con Auth0**, **inventario**, **facturas con OCR**, **preferencias del hogar** y **recetas sugeridas** funcionando, así que ya puedes conectarte a algo real.

> 🆕 **Novedades de esta versión** (si ya venías usando el backend):
> - **Preferencias del hogar** (`GET` / `PUT /preferencias`) y **recetas sugeridas** (`POST /recomendaciones/recetas`) con botón de "¿te sirvió?". Todo está en la sección 6.
> - Recetas: ya hay botón de **"otras recetas"** (`{"nuevas": true}`), y si no queda ninguna receta válida llega una **lista vacía con un `mensaje`** para mostrar (no es un error). Ver sección 6.
> - Hay un servicio nuevo en Docker: corre `docker compose up -d db redis` en lugar de solo `db` (sección 2). Si no levantas Redis, el backend funciona igual, pero sin caché.
> - Después de hacer `git pull`: `pip install -r requirements-dev.txt` (hay dependencias nuevas), `alembic upgrade head` (hay tablas nuevas) y vuelve a generar los tipos (sección 7).
>
> De la versión anterior: endpoints de facturas (sección 5), categorías como lista cerrada (sección 4), `es_alimento` y el filtro `GET /inventario?solo_alimentos=true`.

---

## 1. Estado del backend

| Funcionalidad | Estado |
|---|---|
| Login con Auth0 (usuario y hogar se crean solos en el primer login) | ✅ Listo |
| Inventario: listar, crear, ver, editar, borrar ítems | ✅ Listo |
| Subir factura + OCR, revisar y confirmar | ✅ Listo |
| Preferencias del hogar (dieta, alergias, gustos) | ✅ Listo |
| Recomendación de recetas | ✅ Listo |
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

cp .env.example .env               # te paso los valores de Auth0 y la API key de Gemini por privado

docker compose up -d db redis      # Postgres y Redis (caché de recetas)
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
| GET | `/preferencias` | Preferencias del hogar (o las de por defecto, si nunca las guardó) | `200` |
| PUT | `/preferencias` | Guarda las preferencias (reemplaza todas) | `200` / `422` |
| POST | `/recomendaciones/recetas` | Sugiere hasta 3 recetas con lo que hay en el inventario | `201` / `409` / `503` |
| POST | `/recomendaciones/{id}/feedback` | Guarda si una receta le sirvió al usuario | `204` / `404` / `422` |

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
| `409` | En facturas: ya fue confirmada. En recetas: no hay alimentos en el inventario | Facturas: "esta factura ya está en tu inventario". Recetas: mostrar el `detail` con botones a "agregar producto" y "subir factura" |
| `413` | La imagen pesa más de 10 MB | Pedir una foto más liviana (o comprimirla en el front antes de subirla) |
| `415` | El archivo no es JPEG, PNG ni WebP, o no es una imagen | Pedir otra foto |
| `422` | Datos inválidos (ej. cantidad negativa, categoría fuera de la lista) | Mostrar el error en el formulario. El detalle viene en `detail` |
| `503` | La IA de recetas no respondió | Mostrar el `detail` y un botón de "intentar de nuevo" |

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

## 6. Preferencias y recetas

### Preferencias (`GET` / `PUT /preferencias`)

Son del **hogar** (las comparten todos sus usuarios) y las usa el recomendador de recetas. Si el hogar nunca las guardó, `GET` devuelve estos valores por defecto:

```json
{
  "dieta": "omnivora",
  "alergias": [],
  "no_le_gusta": [],
  "porciones": 2,
  "tiempo_max_minutos": null
}
```

`PUT` recibe ese mismo objeto y devuelve lo que quedó guardado. **Reemplaza todo**: un campo que no mandes vuelve a su valor por defecto. Así que manda siempre el formulario completo.

| Campo | Valores | En la UI |
|---|---|---|
| `dieta` | `omnivora`, `vegetariana`, `vegana`, `pescetariana` | Radio buttons o `<select>` |
| `alergias` | Lista con cualquiera de: `lacteos`, `gluten`, `huevo`, `mani`, `frutos_secos`, `mariscos`, `pescado`, `soya` | Checkboxes. Otro valor responde `422` |
| `no_le_gusta` | Texto libre, máximo 20 elementos de hasta 60 caracteres. Los repetidos se quitan solos | Input de "chips" o etiquetas (cilantro, berenjena…) |
| `porciones` | Entero de 1 a 12 | Stepper − / + |
| `tiempo_max_minutos` | Entero de 5 a 600, o `null` (sin límite) | `<select>`: 15, 30, 45, 60 min, "sin límite" |

### Recetas (`POST /recomendaciones/recetas`)

El backend toma los **alimentos** del inventario (`es_alimento: true`, sin vencer) y las preferencias del hogar. Tarda **unos segundos** la primera vez (llama a la IA; si ninguna receta sirve, reintenta una vez, así que puede tardar el doble) y es casi instantáneo si nada cambió (caché). Muestra un "pensando recetas…".

El body es **opcional**:

| Body | Cuándo | Qué hace |
|---|---|---|
| ninguno, o `{"nuevas": false}` | Al abrir la pantalla de recetas | Si el inventario y las preferencias no cambiaron, devuelve las mismas recetas de antes (caché) |
| `{"nuevas": true}` | Botón **"🔄 Otras recetas"** | No usa la caché y le pide a la IA recetas distintas a las últimas que vio el hogar. Desde ahí, esas nuevas son las que salen al abrir la pantalla |

```json
{
  "recomendacion_id": 31,
  "recetas": [
    {
      "titulo": "Calentado de arroz con huevo",
      "descripcion": "Un desayuno rápido para aprovechar el arroz que sobró.",
      "tiempo_minutos": 20,
      "porciones": 2,
      "ingredientes": [
        { "nombre": "Arroz", "cantidad": 2, "unidad": "taza", "item_id": 7 },
        { "nombre": "Cebolla larga", "cantidad": 1, "unidad": "unidad", "item_id": null },
        { "nombre": "Sal", "cantidad": null, "unidad": null, "item_id": null }
      ],
      "pasos": ["Picar la cebolla.", "Sofreír la cebolla y agregar el arroz."],
      "por_que": "Usa el arroz que vence mañana.",
      "usa_proximos_a_vencer": [
        { "item_id": 7, "nombre": "Arroz blanco", "dias_para_vencer": 1 }
      ],
      "ingredientes_faltantes": ["Cebolla larga", "Sal"]
    }
  ],
  "aviso": "Verifica siempre los ingredientes si tienes alergias: las recetas son generadas por IA.",
  "mensaje": null,
  "cache": "miss",
  "latencia_ms": 4120,
  "modelo": "gemini-2.5-flash"
}
```

| Campo | Qué es | Qué hacer en la UI |
|---|---|---|
| `recetas` | **Hasta** 3. Pueden ser menos, incluso 0: el backend descarta las que tengan un alérgeno declarado, no cumplan la dieta o se pasen del tiempo máximo en más de un 20 % | Tarjetas |
| `mensaje` | `null` si hay recetas. Si `recetas` viene vacía, trae una explicación lista para mostrar | Con lista vacía: mostrar el `mensaje` (no es un error, llega con `201`) y los botones "Otras recetas" y "Editar preferencias" |
| `ingredientes[].item_id` | Id del ítem del inventario que usa, o `null` si hay que comprarlo (o es un básico como sal o aceite) | Marcar con ✓ "lo tienes" los que tienen `item_id` |
| `usa_proximos_a_vencer` | Ítems del inventario que vencen en 3 días o menos y que la receta usa | **Destacarlo** en la tarjeta ("🕒 Usa: Arroz blanco, vence mañana"). Es el punto central de la app |
| `ingredientes_faltantes` | Nombres de los ingredientes con `item_id: null` | Una sección "Te falta" |
| `por_que` | Explicación de la IA de por qué la receta aprovecha lo que está por vencer | Debajo del título |
| `aviso` | Texto fijo de seguridad | **Mostrarlo siempre**, visible, en la pantalla de recetas |
| `recomendacion_id` | Id de esta sugerencia | Guárdalo para el feedback |
| `cache`, `latencia_ms`, `modelo` | Datos técnicos para las métricas del artículo | No mostrarlos al usuario (si acaso en un modo debug) |

- Pedir recetas de nuevo con el mismo inventario y las mismas preferencias devuelve **las mismas recetas** (caché de un día). Para otras, usa `{"nuevas": true}`. Si cambia algo del inventario de alimentos (nombre, cantidad, fecha) o de las preferencias, salen recetas nuevas solas.
- Ejemplo de lista vacía:

  ```json
  {
    "recomendacion_id": 32,
    "recetas": [],
    "aviso": "Verifica siempre los ingredientes si tienes alergias: las recetas son generadas por IA.",
    "mensaje": "No encontramos recetas que cumplan tus preferencias con lo que tienes en el inventario. Intenta pedir otras recetas, agrega productos o revisa tus preferencias.",
    "cache": "miss",
    "latencia_ms": 8350,
    "modelo": "gemini-2.5-flash"
  }
  ```
- Con `409` (sin alimentos), el `detail` ya trae un mensaje listo para mostrar.

### Feedback (`POST /recomendaciones/{id}/feedback`)

Pon en cada tarjeta un 👍 / 👎 de "¿te sirvió esta receta?". Es la métrica de "relevancia percibida" del artículo, así que es importante que esté en la demo.

```json
{ "receta_indice": 0, "util": true }
```

- `receta_indice` es la posición de la receta en la lista `recetas` (0, 1 o 2).
- Responde `204` sin contenido. Si el usuario cambia de opinión, manda otra vez: la última gana.
- `404` si la recomendación no existe o es de otro hogar; `422` si el índice no corresponde a ninguna receta.

---

## 7. Tipos de TypeScript automáticos

No escribas los tipos a mano: se generan desde el backend, y así nunca quedan desincronizados.

```bash
npm i -D openapi-typescript
npx openapi-typescript http://localhost:8000/openapi.json -o src/api/schema.d.ts
```

Vuelve a correrlo cada vez que te avise que cambió algún endpoint. Si quieres, agrégalo como script `"gen:api"` en el `package.json`.

---

## 8. Pantallas para ir arrancando

Lo que ya puedes hacer contra el backend real:

1. **Login / logout** con Auth0.
2. **Inventario**: lista de ítems, resaltando los que vencen en los próximos 3 días. Con un filtro "solo alimentos" (`?solo_alimentos=true`) o pestañas comida / otros.
3. **Crear y editar ítem**: formulario con nombre, categoría (un `<select>` con la lista cerrada), cantidad, unidad y fecha de vencimiento.
4. **Borrar ítem**, con confirmación.
5. **Subir factura**: tomar foto o subir imagen y mostrar un "procesando…" (tarda unos segundos).
6. **Validar factura**: la lista de ítems detectados, editable, con los renglones `revisar: true` resaltados y el aviso de `requiere_revision` arriba. El usuario corrige, agrega fechas de vencimiento y confirma. Es la pantalla más importante de la demo.
7. **Historial de facturas** (`GET /facturas`): supermercado, fecha, total y estado; las pendientes se pueden abrir para terminar de validarlas.
8. **Preferencias**: dieta, alergias (checkboxes), lo que no le gusta, porciones y tiempo máximo. Conviene pedirlas en el onboarding, justo después del primer login.
9. **Recetas sugeridas**: hasta 3 tarjetas con ingredientes ("lo tienes" / "te falta") y pasos, destacando los productos próximos a vencer, con el aviso de alergias visible, el 👍 / 👎 en cada una y un botón "Otras recetas". Ojo con el estado de lista vacía (`mensaje`).

Lo que viene, y que puedes maquetar con datos falsos mientras tanto:

10. **Vista supermercado**: un panel con la demanda agregada por categoría y zona.

---

## 9. Acuerdos de trabajo

- Trabajamos con **ramas + PR** (`feat/login`, `feat/inventario`…). Nada directo a `main`.
- Si necesitas un endpoint o un campo que no existe, me escribes y lo agregamos. No lo resuelvas con lógica rara en el front.
- El **despliegue del frontend** va en Vercel; lo configuramos cuando tengamos las primeras pantallas.
- Al final, tú grabas el **video de la demo**, así que piensa en el flujo desde ya: login → subir factura → validar → inventario → recetas.

Cualquier duda, me escribes. 🚀