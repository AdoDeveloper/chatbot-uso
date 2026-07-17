# Manual de usuario

Guía de uso del panel administrativo del chatbot de la Universidad de Sonsonate.

> Este manual está dirigido al personal que administra el chatbot: carga de
> contenido, configuración del asistente y seguimiento de su uso. No requiere
> conocimientos de programación.

---

## 1. Acceso al sistema

### 1.1 Iniciar sesión

1. Abra el panel en la dirección proporcionada por su institución.
2. Ingrese su correo y contraseña.
3. Pulse **Iniciar sesión**.

Si su cuenta es nueva, el sistema le pedirá **cambiar la contraseña** en el
primer acceso. Establezca una contraseña personal (mínimo 8 caracteres, con
una mayúscula y un número).

### 1.2 Invitaciones

Los administradores pueden invitar a nuevos usuarios. El invitado recibe un
**correo con un enlace** para crear su cuenta. El enlace expira pasado un tiempo;
si caduca, debe solicitarse una nueva invitación.

### 1.3 Roles

Cada usuario tiene un **rol** que determina qué puede ver y hacer. Los roles
base son:

| Rol | Acceso |
| --- | --- |
| Administrador | Acceso total al sistema |
| Editor | Gestión de contenido y base de conocimiento |
| Lector | Solo lectura: estadísticas e historial |

Un administrador puede crear roles personalizados y ajustar sus permisos.

---

## 2. Panel principal (Inicio)

Al entrar se muestra el **panel principal** con un resumen del estado del sistema:
consultas del día, tasa de resolución, fuentes activas y accesos rápidos a las
tareas más comunes.

Si el sistema está recién instalado, aparece un **asistente de configuración**
que guía los pasos iniciales en orden:

1. Conectar un proveedor de IA.
2. Activar y probar el modelo.
3. Subir el primer documento.
4. Aprobar el documento.
5. Probar una pregunta.

---

## 3. Conocimiento (base de contenido)

El chatbot solo responde con la información que usted le proporciona. Esta
sección gestiona ese contenido.

### 3.1 Documentos

En **Conocimiento → Documentos** puede:

- **Subir documentos**: PDF, DOCX, XLSX, CSV o TXT. Arrastre los archivos o
  pulse para seleccionarlos. Puede subir varios a la vez.
- **Seguir el progreso**: cada documento pasa por las etapas de extracción,
  fragmentación e indexación. El estado se actualiza en tiempo real.
- **Revisar y aprobar**: tras procesarse, el documento queda en estado
  *pendiente de revisión*. Hasta que un administrador lo **apruebe**, el chatbot
  no lo usa. Esto evita publicar contenido sin verificar.
- **Rechazar**: si el contenido no es correcto, puede rechazarse (queda
  archivado, no se elimina).

### 3.2 Fragmentos (chunks)

Cada documento se divide en **fragmentos** para que el chatbot pueda buscar en
él. Desde el detalle de un documento puede revisar sus fragmentos, ver
advertencias automáticas (fragmento muy corto, muy largo, con datos personales)
y descartar fragmentos individuales que no deban usarse.

### 3.3 Preguntas frecuentes (FAQ)

Las FAQ son pares de pregunta y respuesta que se crean directamente desde el
panel, sin subir un archivo. A diferencia de los documentos, **se aprueban
automáticamente** al crearse.

### 3.4 Consulta

La pantalla **Consulta** permite hacer una pregunta de prueba directamente
contra la base de conocimiento para ver qué fragmentos recupera el sistema, sin
generar una respuesta completa. Útil para verificar que un documento se indexó
bien.

---

## 4. Configuración del asistente

### 4.1 Proveedores de IA

En **Configuración → Proveedores** se conectan los modelos de lenguaje (Groq,
OpenAI, Google Gemini, Anthropic, o modelos locales como Ollama). Para cada
proveedor:

- Se introduce la API key (se guarda cifrada).
- Se puede **probar** la conexión con un mensaje de prueba.
- Se ordena la **cadena de proveedores** arrastrando: si el primero falla, el
  sistema intenta con el siguiente.

### 4.2 Asistente

Define el comportamiento del chatbot: nombre, mensaje de bienvenida,
instrucciones (prompt del sistema), número de fragmentos a recuperar,
temperatura y mensajes para casos especiales (saludo, sin información,
solicitud bloqueada).

### 4.3 Filtros de seguridad

Gestiona los patrones que detectan intentos de manipulación del chatbot
(inyección de instrucciones). Incluye patrones predefinidos por el sistema y
permite crear patrones personalizados.

### 4.4 Escalamiento

Configura cuándo una conversación debe derivarse a una persona. Las reglas se
basan en disparadores como: sin respuesta tras N segundos, solicitud explícita
del usuario, proporción alta de valoraciones negativas, palabras clave, o
detección de bucles. Incluye una herramienta para **probar reglas** y un envío
de **correo de prueba** para verificar las notificaciones.

### 4.5 Integraciones

Muestra el estado del servidor de correo (SMTP) y permite enviar un correo de
prueba. La configuración del servidor de correo se gestiona a nivel del sistema.

### 4.6 Widget

Configura el chat embebible que se coloca en el sitio web: colores, posición,
mensaje de bienvenida, sugerencias, dominios permitidos y opciones de
visualización. Genera el código de integración para el sitio.

### 4.7 Playground y Publicaciones

- **Playground**: prueba el chatbot tal como lo vería un visitante, con la
  configuración en borrador.
- **Publicaciones**: gestiona el ciclo de publicación. Los cambios se preparan
  en borrador y se **publican** a producción cuando están listos. El sistema
  guarda una versión **automáticamente** cada vez que se modifica la
  configuración (proveedores, asistente, widget, escalamiento, etc.), además de
  los puntos de restauración que se crean manualmente. En cualquier momento se
  puede volver a una versión anterior.

---

## 5. Conversaciones

### 5.1 Historial

En **Conversaciones** se revisa todo el historial de interacciones: mensajes,
fuentes citadas, latencia, valoración (👍/👎) y ruta seguida por el sistema.
Se pueden filtrar, etiquetar y exportar (CSV/PDF).

### 5.2 Pendientes y escalamientos

- **Pendientes**: conversaciones que el sistema marcó para atención humana.
- **Escalamientos**: gestión de las conversaciones derivadas, con asignación a
  responsables y seguimiento hasta su resolución.

---

## 6. Estadísticas y reportes

### 6.1 Estadísticas

Métricas de uso del chatbot: consultas por periodo, tasa de resolución,
latencia, canales, dispositivos, páginas de origen, temas más consultados,
mapa de calor de horarios y **valoración de respuestas** (positivas/negativas).

### 6.2 Reportes

Genera y descarga reportes en PDF para el rango de fechas que se indique:
Ejecutivo, Uso y Temas, Escalamientos y Base de Conocimiento. Cada reporte
incluye portada institucional, un resumen con los hallazgos del período y
gráficas de tendencia y distribución.

---

## 7. Grupos Sistema y Acceso

El menú lateral organiza todo en grupos: **Principal**, **Conocimiento**,
**Chatbot** (secciones 4.1 a 4.7), **Sistema** y **Acceso**. Los tres últimos
son plegables: haga clic en el nombre del grupo para expandirlo u ocultarlo, y
se muestran según los permisos de cada usuario.

### 7.1 Acceso (usuarios, roles, permisos, SSO)

- **Usuarios**: alta, edición y desactivación de cuentas.
- **Roles**: creación y edición de roles personalizados (los del sistema son
  fijos).
- **Permisos**: matriz que define qué puede hacer cada rol por módulo.
- **Inicio de sesión**: acceso con cuentas corporativas de Microsoft 365 (si
  está configurado).

### 7.2 Estado

Salud en vivo de los servicios (base de datos, caché, vector store, modelo de
embeddings) con uptime y percentiles de respuesta. Incluye la configuración del
**caché de respuestas** (activación, vigencia en horas y umbral de similitud) y
herramientas de mantenimiento:

- **Sincronizar Qdrant ↔ BD**: elimina fragmentos huérfanos del índice.
- **Limpiar caché**: borra el caché de respuestas.
- **Limpiar P99**: elimina mediciones anómalas que distorsionan las métricas.

### 7.3 Cuotas

Límites de uso del chat por minuto y por hora, editables directamente desde el
panel, con la tendencia de consumo y la lista de usuarios que alcanzaron el
límite.

### 7.4 Notificaciones

- **Reglas**: qué eventos disparan una notificación (servicio caído, proveedor
  caído, etc.).
- **Canales**: estado del correo saliente.

---

## 8. Actividad (auditoría y seguridad)

- **Auditoría**: registro de todas las acciones realizadas en el sistema (quién,
  qué, cuándo, desde qué IP).
- **Seguridad**: resumen de eventos de seguridad e intentos de acceso fallidos.
- **Inyecciones**: intentos de manipulación del chatbot detectados por los
  filtros, agrupados por categoría.

---

## 9. Preguntas frecuentes del administrador

**¿Por qué el chatbot dice que no tiene información?**
Verifique que el documento esté **aprobado** (no solo subido) y que haya al
menos un proveedor de IA **activo**.

**Subí un documento pero no aparece en las respuestas.**
Tras subirlo debe **aprobarlo** en Conocimiento → Documentos. Solo el contenido
aprobado es visible al chatbot.

**Cambié la configuración del asistente pero el widget no cambia.**
Los cambios se preparan en borrador. Debe **publicarlos** desde Publicaciones
para que lleguen al widget en producción.

**Un usuario no recibió el correo de invitación.**
Revise la carpeta de spam del destinatario. El correo se envía desde la cuenta
configurada en el servidor; algunos proveedores lo filtran.

**¿Cómo derivo conversaciones a una persona?**
Configure reglas de escalamiento en Configuración → Escalamiento. Las
conversaciones derivadas aparecen en Conversaciones → Pendientes.
