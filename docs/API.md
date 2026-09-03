# Referencia de API

API REST del backend. Prefijo base: `/api/v1`.

---

## Convenciones

- **Autenticación**: la mayoría de endpoints requieren un token JWT en la
  cabecera `Authorization: Bearer <token>`. Los endpoints públicos del widget
  usan en su lugar una API key (`X-Widget-Key`).
- **Autorización**: los endpoints administrativos exigen un permiso RBAC
  concreto `(módulo.acción)`; un rol sin ese permiso recibe `403`.
- **Formato**: peticiones y respuestas en JSON, salvo subida de archivos
  (multipart) y las descargas de reportes y exportaciones (PDF/CSV).
- **Códigos**: `200` OK, `201` creado, `204` sin contenido, `401` no
  autenticado, `403` sin permiso, `404` no encontrado, `409` conflicto, `422`
  validación, `429` límite de tasa.

### Documentación interactiva

FastAPI genera Swagger UI y ReDoc automáticamente desde el código
(`app/main.py`), pero quedan **deshabilitados en producción** a propósito
(`ENVIRONMENT=production` → `docs_url=None`) para no exponer la superficie
completa de la API. Solo están disponibles en un entorno con
`ENVIRONMENT` distinto de `production`, en `/api/docs` (Swagger) y
`/api/redoc`. Este documento es la referencia válida en producción.

---

## Autenticación (`/auth`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/auth/providers` | Métodos de login disponibles (credenciales, Microsoft) |
| POST | `/auth/login` | Autenticar y emitir par de tokens |
| POST | `/auth/refresh` | Rotar el refresh token por uno nuevo |
| POST | `/auth/logout` | Revocar la sesión actual |
| GET | `/auth/me` | Datos del usuario autenticado |
| POST | `/auth/change-password` | Cambiar la propia contraseña |
| POST | `/auth/microsoft/callback` | Callback de OAuth de Microsoft 365 |
| GET | `/auth/onboarding-status` | Estado del asistente de configuración inicial |
| POST | `/auth/onboarding-dismiss` | Ocultar el asistente de configuración |
| POST | `/auth/onboarding-reset` | Volver a mostrar el asistente de configuración |
| GET | `/auth/invite/{token}` | Información pública de una invitación |
| POST | `/auth/invite/{token}/accept` | Aceptar invitación y crear cuenta |

## Chat (`/chat`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST | `/chat` | Conversación con el chatbot (respuesta única completa, sin streaming) |

## Conocimiento - Fuentes (`/sources`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/sources` | Listar fuentes |
| GET | `/sources/upload-limits` | Límite de tamaño de archivo configurado (MB) |
| POST | `/sources/upload` | Subir un documento e iniciar ingestión |
| POST | `/sources/bulk-upload` | Subir varios documentos |
| GET | `/sources/{id}` | Detalle de una fuente |
| PATCH | `/sources/{id}` | Editar metadatos de una fuente |
| DELETE | `/sources/{id}` | Eliminar una fuente (y sus vectores) |
| POST | `/sources/{id}/replace-file` | Reemplazar el archivo de una fuente existente y reingestar |
| POST | `/sources/{id}/ingest` | Reprocesar la ingestión |
| POST | `/sources/{id}/approve` | Aprobar una fuente para uso |
| POST | `/sources/{id}/reject` | Rechazar una fuente |
| GET | `/sources/{id}/preview` | Vista previa del texto extraído |
| GET | `/sources/{id}/quality` | Métricas de calidad/uso de la fuente |
| POST | `/sources/bulk/delete` | Eliminar varias fuentes |
| POST | `/sources/bulk/reingest` | Reprocesar varias fuentes |
| POST | `/sources/bulk/tag` | Etiquetar varias fuentes |

## Conocimiento - Fragmentos (`/chunks`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/chunks/source/{source_id}` | Fragmentos de una fuente (paginado) |
| GET | `/chunks/{point_id}` | Detalle de un fragmento |
| PATCH | `/chunks/{point_id}/content` | Editar el contenido de un fragmento |
| POST | `/chunks/{point_id}/discard` | Descartar un fragmento del uso |
| POST | `/chunks/{point_id}/restore` | Restaurar un fragmento descartado |
| GET | `/chunks/{point_id}/history` | Historial de ediciones del fragmento |
| POST | `/chunks/test-query` | Búsqueda de prueba contra los fragmentos |

## Conocimiento - FAQ (`/faq`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/faq` | Listar FAQs |
| POST | `/faq` | Crear FAQ |
| GET | `/faq/{id}` | Detalle de una FAQ |
| PATCH | `/faq/{id}` | Editar una FAQ |
| DELETE | `/faq/{id}` | Eliminar una FAQ |

## Conversaciones (`/conversations`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/conversations` | Listar conversaciones |
| GET | `/conversations/{id}` | Detalle de una conversación con sus mensajes |
| DELETE | `/conversations/{id}` | Eliminar una conversación (borrado físico, con auditoría) |
| PATCH | `/conversations/{id}/status` | Cambiar el estado |
| PUT | `/conversations/{id}/tags` | Asignar etiquetas |
| POST | `/conversations/{id}/csat` | Registrar satisfacción (CSAT) |
| GET | `/conversations/tags` | Etiquetas existentes |
| GET | `/conversations/csat-reason-labels` | Etiquetas legibles de los motivos CSAT configurados |
| POST | `/conversations/bulk` | Acciones en lote |
| GET | `/conversations/export` | Exportar (CSV/PDF) |
| PATCH | `/conversations/messages/{id}/feedback` | Valorar un mensaje |

## Preguntas sin responder (`/unanswered`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/unanswered` | Listar preguntas sin responder (agrupadas) |
| POST | `/unanswered/{id}/resolve` | Marcar como resuelta |
| POST | `/unanswered/{id}/create-faq` | Crear una FAQ a partir de la pregunta |
| GET | `/unanswered/{id}/root-cause` | Análisis de causa raíz |

## Escalamiento (`/escalation`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/escalation/rules` | Listar reglas |
| POST | `/escalation/rules` | Crear regla |
| PATCH | `/escalation/rules/{id}` | Editar regla |
| DELETE | `/escalation/rules/{id}` | Eliminar regla |
| POST | `/escalation/rules/test` | Probar una regla con datos de ejemplo |
| GET | `/escalation/triggers/schemas` | Esquemas de los disparadores disponibles |
| GET | `/escalation/metrics` | Métricas de escalamiento |
| POST | `/escalation/test` | Probar el flujo de escalamiento |
| POST | `/escalation/smtp-ping` | Enviar correo de prueba |

## Analítica (`/analytics`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/analytics/dashboard` | Métricas del panel principal |
| GET | `/analytics/csat` | Satisfacción del usuario (CSAT) agregada, con desglose por motivo |
| GET | `/analytics/comparison` | Comparativa entre periodos |
| GET | `/analytics/timeseries` | Serie temporal de consultas |
| GET | `/analytics/timeline` | Línea de tiempo de actividad |
| GET | `/analytics/latency/timeseries` | Serie temporal de latencia |
| GET | `/analytics/channels` | Distribución por canal |
| GET | `/analytics/devices` | Distribución por dispositivo |
| GET | `/analytics/pages` | Páginas de origen |
| GET | `/analytics/topics` | Temas más consultados |
| GET | `/analytics/heatmap` | Mapa de calor de horarios |
| GET | `/analytics/routes` | Distribución por ruta RAG |
| GET | `/analytics/feedback` | Valoración de respuestas |
| GET | `/analytics/cache` | Estadísticas de caché |
| GET | `/analytics/sources/quality` | Calidad de las fuentes |
| GET | `/analytics/quality` | Calidad de las respuestas del asistente (context relevance, faithfulness, answer relevance) |
| POST | `/analytics/export` | Exportar datos |
| POST | `/analytics/reports` | Generar reporte |

## Auditoría (`/audit`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/audit/logs` | Registros de auditoría (filtrable) |
| GET | `/audit/logs/{id}` | Detalle de un registro |
| GET | `/audit/logs/export` | Exportar registros |
| GET | `/audit/actors` | Actores que han generado registros |

## Notificaciones (`/notifications`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/notifications` | Historial de notificaciones enviadas (todos los canales), paginado |
| GET | `/notifications/rules` | Listar reglas de notificación |
| PUT | `/notifications/rules/{id}` | Editar regla |
| GET | `/notifications/rules/email/status` | Estado del canal de correo (activo/inactivo) |
| PUT | `/notifications/rules/email/toggle` | Activar/desactivar el canal de correo |
| GET | `/notifications/report-schedule` | Programación vigente de reportes automáticos |
| PUT | `/notifications/report-schedule` | Editar la programación de reportes |
| GET | `/notifications/inbox` | Bandeja de notificaciones |
| POST | `/notifications/inbox/{id}/read` | Marcar una como leída |
| POST | `/notifications/inbox/mark-all-read` | Marcar todas como leídas |

> `POST /integrations/smtp/test` cubre el envío de un correo de prueba (ver
> sección Integraciones) — no existe un endpoint de prueba dedicado bajo
> `/notifications`.

## Salud del sistema (`/health`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/health` | Estado básico |
| GET | `/health/live` | Liveness probe |
| GET | `/health/ready` | Readiness probe |
| GET | `/health/detailed` | Estado detallado por servicio |
| GET | `/health/history` | Histórico de mediciones |
| GET | `/health/uptime` | Uptime y percentiles por servicio |
| GET | `/health/incidents` | Historial de incidentes |
| POST | `/health/snapshot` | Tomar una medición ahora |

## Widget público (`/widget`)

| Método | Ruta | Descripción | Auth |
| --- | --- | --- | --- |
| GET | `/widget/config` | Configuración del widget (admin) | JWT |
| PUT | `/widget/config` | Editar configuración | JWT |
| GET | `/widget/csat-reasons` | Listar motivos seleccionables de la encuesta CSAT | JWT |
| POST | `/widget/csat-reasons` | Crear un motivo | JWT |
| PATCH | `/widget/csat-reasons/{id}` | Editar un motivo (texto, activo/inactivo) | JWT |
| DELETE | `/widget/csat-reasons/{id}` | Eliminar un motivo | JWT |
| PUT | `/widget/csat-reasons/reorder` | Reordenar los motivos | JWT |
| GET | `/widget/embed-code` | Código de integración | JWT |
| POST | `/widget/regenerate-key` | Regenerar la API key | JWT |
| GET | `/widget/public/config` | Configuración pública | API key |
| POST | `/widget/public/chat` | Chat desde el widget | API key |
| POST | `/widget/public/csat` | Registrar CSAT | API key |
| POST | `/widget/public/escalation/contact` | Solicitud de contacto | API key |
| PATCH | `/widget/public/messages/{id}/feedback` | Valorar respuesta | API key |

---

## Endpoints administrativos

Requieren permisos RBAC específicos. Organizados por dominio, sin un prefijo
común: cada grupo vive en su propia carpeta bajo `backend/app/api/v1/`.

### Acceso - usuarios e invitaciones (`access/`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/users` | Listar usuarios |
| GET | `/users/summary` | Conteos agregados del equipo (total, activos, sin acceso, admins) |
| GET | `/users/{id}` | Detalle de usuario |
| PATCH | `/users/{id}` | Editar usuario |
| DELETE | `/users/{id}` | Eliminar usuario |
| POST | `/users/{id}/reset-password` | Generar una contraseña temporal para el usuario |
| GET | `/users/invitations` | Listar invitaciones |
| POST | `/users/invitations` | Crear invitación (envía correo) |
| POST | `/users/invitations/{id}/resend` | Reenviar el correo de invitación |
| DELETE | `/users/invitations/{id}` | Revocar invitación |
| DELETE | `/users/invitations/{id}/permanent` | Eliminar definitivamente una invitación no activa |
| GET | `/rbac/roles` | Listar roles del sistema |
| GET | `/rbac/my-permissions` | Permisos del usuario actual |

> Los roles (`admin`/`editor`/`viewer`) son fijos, definidos en código
> (`SYSTEM_ROLES`) — no existe un endpoint para crear, editar o eliminar
> roles ni para conceder permisos individuales

### Proveedores de IA (`providers/`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/providers` | Listar proveedores |
| POST | `/providers` | Crear proveedor |
| PATCH | `/providers/{id}` | Editar proveedor |
| DELETE | `/providers/{id}` | Eliminar proveedor |
| POST | `/providers/{id}/test` | Probar un proveedor existente |
| POST | `/providers/test` | Probar una configuración no guardada |
| GET | `/providers/{id}/models` | Modelos disponibles del proveedor |
| POST | `/providers/models` | Consultar modelos por configuración |
| POST | `/providers/reorder` | Reordenar la cadena de proveedores |

### Configuración del asistente (`settings/`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/settings` | Configuración del asistente |
| PUT | `/settings` | Actualizar configuración |
| GET | `/settings/export` | Exportar configuración |
| POST | `/settings/import` | Importar configuración |

### Versiones y publicación (`versions/`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/versions` | Listar versiones de configuración |
| POST | `/versions` | Crear punto de restauración |
| GET | `/versions/{id}` | Detalle de una versión |
| GET | `/versions/{id}/diff` | Diferencias con la versión activa |
| POST | `/versions/{id}/rollback` | Restaurar una versión |
| POST | `/versions/deploy` | Publicar a producción |
| GET | `/versions/deploy/config` | Configuración de despliegue activa |
| GET | `/versions/deploy/status` | Estado del despliegue |

### Integraciones y autenticación (`integrations/`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/integrations/smtp` | Estado del servidor SMTP |
| POST | `/integrations/smtp/test` | Enviar correo de prueba |
| GET | `/integrations/oauth` | Configuración OAuth (Microsoft) |
| PUT | `/integrations/oauth` | Actualizar OAuth |
| GET | `/integrations/auth-methods` | Métodos de autenticación activos |
| PUT | `/integrations/auth-methods` | Activar/desactivar métodos |

### Sistema - caché, cuotas, seguridad, guardrails y mantenimiento (`system/`)

| Método | Ruta | Descripción |
| --- | --- | --- |
| GET | `/cache/stats` | Estadísticas del caché |
| GET | `/cache/entries` | Entradas cacheadas |
| PATCH | `/cache/config` | Configurar el caché |
| DELETE | `/cache/entry/{key}` | Eliminar una entrada |
| DELETE | `/cache/clear` | Vaciar todo el caché |
| GET | `/rate-limits/config` | Configuración de límites |
| PUT | `/rate-limits/config` | Actualizar límites |
| GET | `/rate-limits/usage` | Uso actual |
| GET | `/rate-limits/throttled` | IPs cercanas o sobre el límite |
| DELETE | `/rate-limits/reset/{ip}` | Restablecer los contadores de una IP |
| GET | `/security/summary` | Resumen de seguridad |
| GET | `/security/login-failures` | Intentos de login fallidos |
| GET | `/security/injections/by-category` | Inyecciones por categoría |
| GET | `/security/injections/samples` | Muestras de inyecciones |
| GET | `/guardrails/config` | Configuración de guardrails |
| PATCH | `/guardrails/config` | Actualizar configuración |
| GET | `/guardrails/patterns` | Listar patrones de inyección |
| POST | `/guardrails/patterns` | Crear patrón personalizado |
| PATCH | `/guardrails/patterns/{id}` | Editar patrón |
| DELETE | `/guardrails/patterns/{id}` | Eliminar patrón |
| GET | `/guardrails/patterns/{id}/impact` | Impacto de un patrón |
| POST | `/guardrails/test` | Probar un texto contra los filtros |
| GET | `/guardrails/injection-log` | Registro de inyecciones detectadas |
| POST | `/maintenance/sync-qdrant` | Sincronizar Qdrant con la BD |
| DELETE | `/maintenance/health-snapshots/outliers` | Purgar mediciones anómalas |
| POST | `/alerts/run` | Ejecutar la evaluación de alertas |
