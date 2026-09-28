# Manual de usuario

Guía de uso del panel administrativo del chatbot institucional.

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
primer acceso. Establezca una contraseña personal (entre 8 y 72 caracteres, con
una mayúscula y un número).

### 1.2 Invitaciones

Los administradores pueden invitar a nuevos usuarios. El invitado recibe un
**correo con un enlace** para crear su cuenta. El enlace expira pasado un tiempo;
si caduca, debe solicitarse una nueva invitación. No se puede invitar a un
correo que ya tiene cuenta.

### 1.3 Roles

Cada usuario tiene un **rol** que determina qué puede ver y hacer. Los roles
base son:

| Rol | Acceso |
| --- | --- |
| Administrador | Acceso total al sistema |
| Editor | Gestión de contenido y base de conocimiento |
| Lector | Solo lectura: estadísticas e historial |

Estos tres roles son fijos, con sus permisos ya definidos por el sistema: no
se pueden crear roles adicionales ni cambiar qué puede hacer cada uno (ver
7.1).

---

## 2. Panel principal (Inicio)

Al entrar se muestra el **panel principal** con un resumen del estado del sistema:
consultas del día, tasa de resolución, fuentes activas y accesos rápidos a las
tareas más comunes. La **tasa de resolución** es el porcentaje de preguntas
sin respuesta de la semana que el equipo ya atendió (por ejemplo, creando una
FAQ); si en la semana no hubo preguntas sin respuesta, muestra 100%.

El panel se puede usar desde el celular o la tablet: el menú lateral se
abre con el botón de la esquina superior izquierda, y las tablas anchas
(auditoría, documentos, usuarios) se desplazan de lado dentro de su tarjeta.

Si el sistema está recién instalado, aparece un **asistente de configuración**
que guía los pasos iniciales en orden:

1. Conectar un proveedor de IA.
2. Activar y probar el modelo.
3. Subir el primer documento.
4. Aprobar el documento.
5. Probar una pregunta en la previsualización del asistente.

Cada paso enlaza directamente a la pantalla donde se completa.

---

## 3. Conocimiento (base de contenido)

El chatbot solo responde con la información que usted le proporciona. Esta
sección gestiona ese contenido.

### 3.1 Documentos

En **Conocimiento → Documentos** puede:

- **Subir documentos**: PDF, DOCX o TXT. Arrastre los archivos o
  pulse para seleccionarlos. Puede subir varios a la vez. El tipo se reconoce
  por la extensión del archivo (.pdf, .docx o .txt); cualquier otra se rechaza.
  Si algunos archivos de una subida múltiple fallan, el panel queda abierto
  solo con esos archivos y el motivo de cada uno, para corregirlos y reintentar.
- **Renombrar**: el nuevo nombre se aplica también a las fuentes que cita el
  asistente en sus respuestas.
- **Seguir el progreso**: cada documento pasa por las etapas de extracción,
  fragmentación e indexación. El estado se actualiza en tiempo real.
- **Revisar y aprobar**: tras procesarse, el documento queda en estado
  *pendiente de revisión*. Hasta que un administrador lo **apruebe**, el chatbot
  no lo usa. Esto evita publicar contenido sin verificar.
- **Rechazar**: si el contenido no es correcto, puede rechazarse (queda
  archivado, no se elimina).
- **Reprocesar**: vuelve a extraer y fragmentar el mismo archivo. Si el
  documento estaba aprobado, sigue aprobado al terminar; mientras se procesa, el
  chatbot no lo usa. Si el reprocesamiento falla, se conserva la versión anterior
  y aparece un aviso junto al estado con el motivo.
- **Reemplazar**: sube una nueva versión del archivo. Como el contenido cambió,
  el documento vuelve a quedar *pendiente de revisión*.
- **Eliminar**: el chatbot deja de usar el documento y se borra su archivo del
  servidor. La eliminación no se puede deshacer.

### 3.2 Fragmentos (chunks)

Cada documento se divide en **fragmentos** para que el chatbot pueda buscar en
él. Desde el menú de cada documento (**Ver fragmentos**) puede revisar sus fragmentos, ver
advertencias automáticas (fragmento muy corto, muy largo, con datos personales)
y descartar fragmentos individuales que no deban usarse; el texto descartado
deja de llegar al asistente, también dentro del contexto que comparte con los
fragmentos vecinos. También puede
**editar** el texto de un fragmento; el cambio se aplica al instante en las
respuestas. Las ediciones y los descartes se conservan al reprocesar el
documento, siempre que el texto original del fragmento no haya cambiado.

### 3.3 Preguntas frecuentes (FAQ)

Las FAQ son pares de pregunta y respuesta que se crean directamente desde el
panel, sin subir un archivo. A diferencia de los documentos, **se aprueban
automáticamente** al crearse.

Una FAQ puede apuntar a una imagen o a un documento PDF publicado en internet.
Para que el asistente lo ofrezca cuando corresponde, describa en la respuesta
qué contiene el enlace, por ejemplo «Los aranceles de Ingeniería en Sistemas
están en este documento: https://…/aranceles.pdf». Una respuesta que solo
contiene la URL hace que el asistente a veces diga que no tiene el dato.

### 3.4 Consulta

La pantalla **Consulta** permite hacer una pregunta de prueba directamente
contra la base de conocimiento para ver qué fragmentos recupera el sistema, sin
generar una respuesta completa. Usa la misma búsqueda que el chat e indica qué
fragmentos considera relevantes el evaluador. Sin elegir fuentes busca en las
mismas fuentes aprobadas que usa el chat; eligiendo fuentes concretas también
puede probar documentos pendientes de revisión antes de aprobarlos. Útil para
verificar que un documento se indexó bien.

---

## 4. Configuración del asistente

### 4.1 Proveedores de IA

En **Configuración → Proveedores** se conectan los modelos de lenguaje (Groq,
OpenAI, Google Gemini, Anthropic, o modelos locales como Ollama). Para cada
proveedor:

- Se introduce la API key (se guarda cifrada). El botón del ojo muestra u
  oculta la clave; al editar un proveedor, muestra la clave guardada y deja
  constancia en Actividad → Auditoría. Si la clave guardada no se puede leer,
  el proveedor aparece con la etiqueta «Reingresar clave».
- Se puede **probar** la conexión con un mensaje de prueba.
- Se ordena la **cadena de proveedores** arrastrando: si el primero falla, el
  sistema intenta con el siguiente. Al quitar o eliminar un proveedor, los
  demás suben de posición y el primero pasa a ser el principal.

Debajo de la lista de proveedores, la tabla **Tipos de proveedor** muestra los
proveedores conocidos con su dirección por defecto. Sirve para agregar un tipo
nuevo (cuando aparece un proveedor no listado) o corregir la dirección de uno
existente si el proveedor cambia su servicio - el cambio se aplica de
inmediato a todos los proveedores conectados de ese tipo.

### 4.2 Asistente

Define el comportamiento del chatbot: nombre, mensaje de bienvenida,
instrucciones (prompt del sistema), número de fragmentos a recuperar,
temperatura y mensajes para casos especiales (saludo, sin información,
solicitud bloqueada).

En la pestaña **Prompt**, «Respuestas con control de fidelidad» indica qué
porcentaje de respuestas se revisa contra los documentos para la métrica de
calidad de Estadísticas. Cada revisión hace dos consultas extra al proveedor de
IA, por eso conviene un valor bajo (20% por defecto); 0% la desactiva.

### 4.3 Filtros de seguridad

Gestiona los patrones que detectan intentos de manipulación del chatbot
(inyección de instrucciones). Incluye patrones predefinidos por el sistema y
permite crear patrones personalizados. Los patrones predefinidos solo actúan
cuando el mensaje se dirige al asistente («olvida tus instrucciones»); una
pregunta como «¿qué pasa si un estudiante ignora las reglas de la biblioteca?»
se responde con normalidad.

El interruptor general (**Filtros activos**) también controla el ocultamiento de
datos personales (correos, teléfonos, tarjetas y cuentas bancarias; el DUI,
el NIT y los teléfonos de El Salvador siempre) en preguntas y respuestas: si
se desactiva, esos datos dejan de ocultarse.

### 4.4 Escalamiento

Configura cuándo una conversación debe derivarse a una persona. Las reglas se
basan en disparadores como:

- **Sin respuesta**: el asistente responde varias veces seguidas (2 por
  defecto) que no tiene la información pedida.
- **Solicitud del usuario**: el visitante pide explícitamente atención humana,
  con frases como «hablar con un agente» o «que me atienda una persona». Una
  pregunta que solo menciona a una persona («¿qué necesita una persona para
  inscribirse?») no la activa. Puede definir frases propias.
- Proporción alta de valoraciones negativas, palabras clave críticas, baja
  confianza de la búsqueda o detección de bucles.

Las palabras clave críticas se comparan como palabras completas, sin distinguir
mayúsculas ni tildes y admitiendo el plural: «queja» detecta «quejas», y «robo»
no se activa con «Robótica».

 Incluye una herramienta para **probar reglas** y un envío
de **correo de prueba** para verificar las notificaciones.

### 4.5 Integraciones

Muestra el estado del servidor de correo (SMTP) y permite enviar un correo de
prueba. La configuración del servidor de correo se gestiona a nivel del sistema.

### 4.6 Widget

Configura el chat embebible que se coloca en el sitio web: colores, posición,
mensaje de bienvenida, sugerencias, etiqueta junto al botón flotante, dominios
permitidos y opciones de visualización. Genera el código de integración para
el sitio.

En pantallas de celular, el chat se abre a pantalla completa. Los límites
de uso del widget se configuran aquí: **mensajes por sesión** (por cada
visitante) y **mensajes por día**, que es un tope **global** para todos los
visitantes; al alcanzarlo, el chat deja de responder a todos hasta el día
siguiente, por lo que conviene dejarlo vacío o con un valor holgado.

### 4.7 Previsualizar e Historial

- **Previsualizar** (Asistente → Previsualizar): prueba el chatbot tal como lo
  vería un visitante, con la configuración vigente. En el celular el chat de
  prueba empieza cerrado; al tocar el botón se abre a pantalla completa, igual
  que el widget real.
- **Historial**: historial de cambios de la configuración. Cada cambio se
  aplica **de inmediato** al widget (no hay un paso de publicación aparte), y
  el sistema guarda una versión **automáticamente** cada vez que se modifica
  algo (proveedores, asistente, widget, escalamiento, etc.), además de los
  puntos de restauración que se crean manualmente. En cualquier momento se
  puede volver a una versión anterior.

---

## 5. Conversaciones

### 5.1 Historial

En **Conversaciones** se revisa todo el historial de interacciones: mensajes,
fuentes citadas, latencia, valoración (👍/👎) y ruta seguida por el sistema.
Se pueden filtrar, etiquetar, exportar (Excel/PDF, con los mismos filtros
aplicados en la lista, incluido el estado) y eliminar de forma
permanente (solo con el permiso correspondiente; la eliminación no se puede
deshacer).

### 5.2 Pendientes y escalamientos

- **Pendientes**: preguntas que el chatbot no pudo responder, agrupadas por
  tema. Cada una puede convertirse en FAQ o marcarse como resuelta; al hacerlo
  también se resuelven las repeticiones idénticas de la misma pregunta.
- **Escalamientos**: gestión de las conversaciones derivadas, con asignación a
  responsables y seguimiento hasta su resolución. Si el visitante dejó su
  correo o WhatsApp, aparece en la tarjeta con un enlace para contactarlo.

---

## 6. Estadísticas y reportes

### 6.1 Estadísticas

Métricas de uso del chatbot: consultas por periodo, tasa de resolución,
latencia, canales, dispositivos, páginas de origen, temas más consultados,
mapa de calor de horarios y **valoración de respuestas** (positivas/negativas).
Todas las secciones siguen el rango de fechas elegido, incluida la comparación
con el periodo anterior (del mismo largo e inmediatamente previo); el mapa de
calor usa su propio selector de ventana.

El selector **Producción / Previsualizar** separa el tráfico real de los
visitantes (widget y API) de las pruebas hechas desde el panel en Asistente →
Previsualizar, incluso cuando la prueba usa la configuración real. Así las
pruebas del personal no se cuentan como consultas de los usuarios.

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
- **Roles**: los tres roles del sistema (Administrador, Editor, Lector) son
  fijos; no se pueden crear roles adicionales.
- **Permisos**: matriz de consulta que muestra qué puede hacer cada rol por
  módulo.
- **Inicio de sesión**: acceso con cuentas corporativas de Microsoft 365 (si
  está configurado). Solo se aceptan cuentas de la organización configurada y
  que ya existan como usuarios del panel. El acceso con contraseña no se puede
  desactivar mientras Microsoft SSO no esté activo, para que nadie quede sin
  poder entrar; y si Microsoft deja de estar operativo después, el acceso con
  contraseña vuelve a funcionar automáticamente.
- **Invitaciones**: crear, reenviar, revocar y aceptar invitaciones queda
  registrado en Actividad → Auditoría.

### 7.2 Estado

Salud en vivo de los servicios (base de datos, caché, vector store, modelo de
embeddings) con uptime y percentiles de respuesta. Incluye la configuración del
**caché de respuestas** (activación, vigencia en horas y umbral de similitud,
entre 0,95 y 0,99) y, en el apartado **Recuperación**, herramientas de
mantenimiento que no hace falta usar en el uso normal:

- **Sincronizar Qdrant ↔ BD**: elimina del índice los fragmentos cuyo documento
  ya no existe.
- **Limpiar caché**: borra el caché de respuestas.
- **Limpiar P99**: elimina mediciones correctas pero anómalamente lentas que
  distorsionan las métricas; las mediciones fallidas se conservan como
  historial de incidentes.

Al desactivar el caché se dejan de reutilizar tanto las respuestas a preguntas
parecidas como las respuestas a preguntas idénticas.

### 7.3 Cuotas

Límites de uso del chat por minuto y por hora, editables directamente desde el
panel, con la tendencia de consumo y la lista de usuarios que alcanzaron el
límite. Los límites se aplican a cada dirección IP por separado; la pestaña de
tendencia muestra las consultas por hora de todo el sitio y marca en rojo las
horas en las que alguna IP fue bloqueada por alcanzar su límite.

### 7.4 Notificaciones

- **Reglas**: qué eventos disparan una notificación (servicio caído, proveedor
  caído, etc.).
- **Canales**: estado del correo saliente.
- **Resumen de preguntas sin responder**: un correo periódico con las preguntas
  que el chatbot no pudo contestar. La cadencia (diaria, semanal, mensual o
  anual) y la hora de envío se configuran aparte; las cifras del correo
  cubren el mismo periodo (el último día, la última semana, el último mes o
  el último año). Si se elige un día que el mes no tiene (por ejemplo, el 31),
  el reporte se envía el último día de ese mes.

Además del correo, las notificaciones llegan a la campana en la esquina
superior del panel. Al abrir una notificación se marca como leída
automáticamente; también puede marcarse individualmente (botón que aparece al
pasar el mouse) o todas a la vez. El historial completo (Configuración →
Notificaciones) agrupa en una sola fila los envíos que salieron por varios
canales a la vez (por ejemplo, correo + varios administradores en la app).

---

## 8. Actividad (auditoría y seguridad)

- **Auditoría**: registro de todas las acciones realizadas en el sistema (quién,
  qué, cuándo, desde qué IP), con la acción descrita en español. Se puede
  filtrar por recurso, persona y fechas, y exportar a Excel o PDF.
- **Seguridad**: resumen de eventos de seguridad e intentos de acceso fallidos.
- **Inyecciones**: intentos de manipulación del chatbot detectados por los
  filtros, agrupados por categoría.

---

## 9. Widget de chat público

Esta sección describe lo que ve un **visitante del sitio institucional**, no
el personal administrador. El widget es el chat embebido que se incrusta en
páginas externas mediante el código de integración (Configuración →
Asistente → Integración).

### 9.1 Uso básico

El widget aparece como una burbuja flotante en una esquina del sitio. Al
hacer clic se abre la ventana de conversación, con el mensaje de bienvenida
configurado y, si están activas, sugerencias rápidas de preguntas frecuentes.
El visitante escribe su pregunta y el asistente responde con base en el
contenido aprobado en la base de conocimiento.

La conversación se conserva en el navegador si el visitante recarga la
página o vuelve más tarde, hasta 4 horas después del último mensaje; pasado
ese tiempo el widget empieza una conversación nueva, de modo que en un equipo
compartido el siguiente visitante no ve la conversación anterior.

### 9.2 Controles sobre cada respuesta

Al pasar el cursor sobre una respuesta del asistente aparecen tres controles:

- **Escuchar en voz alta**: lee la respuesta usando el sintetizador de voz
  del navegador.
- **Copiar**: copia el texto de la respuesta al portapapeles.
- **Valorar (útil / no útil)**: el visitante indica si la respuesta resolvió
  su consulta. Esta valoración queda disponible para el equipo administrador
  en Estadísticas → Retroalimentación.

### 9.3 Imágenes y documentos PDF en las respuestas

Cuando la información aprobada incluye el enlace a una imagen (.png, .jpg,
.jpeg, .gif o .webp) o a un documento PDF relacionado con la pregunta, el
asistente lo incluye en la respuesta:

- **Imágenes**: se muestran dentro de la respuesta, ajustadas al ancho del chat.
- **PDF**: aparecen como un botón con el ícono de documento y su nombre (por
  ejemplo «Aranceles Ingeniería en Sistemas»); si el nombre no está disponible
  se muestra «Documento PDF». Al hacer clic, el documento se abre en una
  pestaña nueva.

El asistente solo comparte imágenes y documentos relacionados con la pregunta
y nunca escribe enlaces que no estén en la información aprobada. Por
seguridad, el contenido de las respuestas se filtra antes de mostrarse: se
eliminan scripts, enlaces `javascript:` y atributos de eventos.

### 9.4 Accesibilidad

Desde el menú de opciones del widget, el botón **Accesibilidad** abre un
panel con dos ajustes que se recuerdan entre visitas (guardados en el
navegador del visitante):

- **Tamaño del texto**: pequeño, normal o grande.
- **Alto contraste**: activa una paleta de colores de mayor contraste.

### 9.5 Encuesta de satisfacción (CSAT)

Al finalizar la conversación (menú de opciones → Finalizar chat), se invita
al visitante a calificarla del 1 al 5, opcionalmente indicar un motivo y
dejar un comentario. Estos datos alimentan el indicador de satisfacción en
Estadísticas. Finalizar el chat cierra esa conversación: al volver a escribir
empieza una nueva, con o sin encuesta.

### 9.6 Solicitar contacto humano (escalamiento)

Cuando una regla de escalamiento se activa (por ejemplo, el visitante pide
hablar con una persona, o el asistente detecta baja confianza en sus
respuestas), el chat muestra una tarjeta ofreciendo derivar la conversación.
Si el visitante pide directamente hablar con una persona, el asistente le
responde que puede dejar su correo o su WhatsApp, sin buscar en los
documentos.
Si el visitante acepta, puede dejar su correo o número de WhatsApp; el
sistema notifica al personal administrador según las reglas configuradas en
Configuración → Escalamiento.

---

## 10. Preguntas frecuentes del administrador

**¿Por qué el chatbot dice que no tiene información?**
Verifique que el documento esté **aprobado** (no solo subido) y que haya al
menos un proveedor de IA **activo**.

**Subí un documento pero no aparece en las respuestas.**
Tras subirlo debe **aprobarlo** en Conocimiento → Documentos. Solo el contenido
aprobado es visible al chatbot.

**Cambié la configuración del asistente pero el widget no cambia.**
Los cambios se aplican de inmediato, sin paso de publicación. Si el widget
sigue igual, recargue la página del sitio donde está incrustado: el navegador
puede tener la versión anterior en caché.

**Un usuario no recibió el correo de invitación.**
Revise la carpeta de spam del destinatario. El correo se envía desde la cuenta
configurada en el servidor; algunos proveedores lo filtran.

**¿Cómo derivo conversaciones a una persona?**
Configure reglas de escalamiento en Configuración → Escalamiento. Las
conversaciones derivadas aparecen en Conversaciones → Pendientes.
