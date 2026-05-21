# Workflow: Refresh de Datasources

## Cuándo aplica este playbook

El usuario pide refrescar una datasource o "actualizar el dashboard X" (lo cual generalmente significa refrescar su datasource subyacente). También aplica para "los datos están viejos" / "no están actualizados" / "trae los datos de hoy".

## Pre-check (siempre)

Antes de cualquier refresh, validar:
- `site_info` funciona (PAT vigente). Si falla → 401 → ver `SKILL.md` para mensaje al usuario.
- Si el usuario mencionó múltiples datasources, confirmar en chat antes de disparar todos los refresh (puede haber rate limits / costos).

## Pasos

### 1. Identificar la(s) datasource(s) a refrescar

Si el usuario:
- **Da el ID directo de la datasource (LUID)** → validar que sea UUID antes de pasarlo. Ir al paso 2.
- **Menciona un nombre** → llamar `list_datasources` y buscar por nombre (case-insensitive substring match en el campo `name`). Si hay múltiples coincidencias, mostrar la lista al usuario y pedir cuál. Si hay 0 coincidencias, decirlo claramente (no inventar).
- **Menciona un workbook** ("refrescá el dashboard de RegionA") → `search_catalog(workbook_filter="RegionA")` para encontrar el workbook, luego `get_workbook_details(entry_id)` para ver qué datasources usa, luego refrescar **solo las publicadas** (`is_published=True` y `connection_class="sqlproxy"`). Las inline/local no se pueden refrescar desde acá.

### 2. Disparar el refresh

```
refresh_datasource(datasource_id="...")
```

Esto retorna un `job_id`. **Importante**: no asumir que terminó — un refresh puede tardar segundos o minutos.

### 3. Esperar y validar (recomendado)

En vez de los dos pasos anteriores por separado, preferir:
```
refresh_and_wait(datasource_id="...", timeout_seconds=600)
```

Esto dispara y espera. Retorna status final. **Importante**: la tool bloquea por hasta 10 minutos por default — si el usuario quiere algo más rápido o asíncrono, decirselo y ofrecer la alternativa `refresh_datasource` + `check_refresh_job`.

Si el status final es:
- `finish_code=0` ("Success") → confirmar al usuario, reportar elapsed time.
- `finish_code=1` ("Failed") → reportar el error y sugerir revisar la conexión a la base de datos subyacente.
- `"timeout"` → no terminó en el tiempo dado. No es necesariamente error — el refresh puede seguir corriendo. Sugerir al usuario chequear con `check_refresh_job(job_id=...)` en 5-10 min.

### 4. (Opcional) Refrescar múltiples

Si el usuario pidió refrescar varias datasources, hacerlo **una por una en serie** (no en paralelo), porque Tableau Cloud aplica rate limits en jobs concurrentes.

## Ejemplo de interacción

**Usuario**: "Refrescá la datasource de Survey RegionA y avisame cuando termine"

**Claude**:
1. Llamar `list_datasources` y buscar "RegionA" o "Survey".
2. Encontrar `Survey-RegionA` con ID `xyz-123`.
3. Llamar `refresh_and_wait(datasource_id="xyz-123")`.
4. Reportar resultado: "Listo, refresh terminado en 47 segundos sin errores."

## Errores comunes

- **"Datasource is not extract"** → la datasource es live (no tiene extract). Refresh no aplica. Explicar al usuario que solo se pueden refrescar datasources con extract.
- **Refresh muy lento** → puede ser un dataset enorme. No es error; sugerir aumentar timeout o correr asincrónico con `refresh_datasource` + `check_refresh_job` después.
