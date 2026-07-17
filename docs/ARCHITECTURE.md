# Arquitectura

Diagramas y explicación del flujo interno del sistema.

---

## 1. Vista general del despliegue

```mermaid
flowchart TB
    subgraph internet["Internet"]
        users["Usuarios finales<br/>(widget en sitio USO)"]
        admin["Personal admin<br/>(panel)"]
    end

    proxy["Reverse Proxy<br/>(Nginx / Caddy)<br/>:443 TLS"]

    subgraph app["Aplicación"]
        front["Frontend Next.js<br/>:3000"]
        back["Backend FastAPI<br/>:8000<br/>(1-2 workers)"]
    end

    subgraph data["Servicios de datos"]
        mysql[("MySQL 8<br/>:3306")]
        redis[("Redis 7<br/>:6379")]
        qdrant[("Qdrant 1.12+<br/>:6333<br/>vectores")]
    end

    subgraph llm["Proveedores LLM externos"]
        groq["Groq"]
        openai["OpenAI"]
        anthropic["Anthropic"]
        gemini["Google Gemini"]
    end

    users -->|HTTPS| proxy
    admin -->|HTTPS| proxy
    proxy -->|/api/*| back
    proxy -->|/| front
    front -.->|fetch| back
    back --> mysql
    back --> redis
    back --> qdrant
    back -.->|httpx| llm
```

**Reglas de exposición**:

- Solo el reverse proxy (puerto 443) está expuesto a internet.
- Backend, frontend y servicios de datos escuchan en `127.0.0.1` o red interna.
- Qdrant y MySQL requieren auth si se exponen a la red local.

---

## 2. Stack tecnológico

```mermaid
flowchart LR
    subgraph fe["Frontend"]
        next["Next.js 15.5<br/>App Router"]
        tw["Tailwind v4<br/>+ shadcn/ui"]
        rq["TanStack Query"]
    end

    subgraph be["Backend"]
        fa["FastAPI 0.115<br/>+ Uvicorn"]
        sa["SQLAlchemy 2<br/>(async)"]
        al["Alembic<br/>(migraciones)"]
        lg["LangGraph<br/>(Adaptive RAG)"]
    end

    subgraph emb["Pipeline RAG"]
        fe2["fastembed<br/>multilingual-e5-large"]
        bm25["Qdrant BM25<br/>(sparse)"]
        rerank["FlashRank<br/>(MultiBERT-L-12)"]
    end

    subgraph guard["Seguridad"]
        presidio["Presidio<br/>(PII español)"]
        regex["Regex<br/>anti-inyección"]
        fernet["Fernet<br/>(secrets at rest)"]
    end

    fe --> be
    be --> emb
    be --> guard
```

| Capa | Tecnología | Versión |
| --- | --- | --- |
| Backend | Python + FastAPI (Uvicorn) | 3.12 / 0.118 |
| ORM | SQLAlchemy async + Alembic | 2.0 |
| Base de datos | MySQL | 8.0 |
| Caché / rate-limit | Redis | 7 |
| Vector DB (cliente) | Qdrant | qdrant-client 1.13.3 |
| Embeddings densos | intfloat/multilingual-e5-large (fastembed) | 1024 dims |
| Embeddings sparse | Qdrant/bm25 (fastembed) | — |
| Reranker | ms-marco-MultiBERT-L-12 (FlashRank) | — |
| RAG | LangGraph Adaptive RAG | — |
| Frontend | Next.js 15 + Tailwind v4 + shadcn/ui | — |
| Widget | Preact + Shadow DOM | — |

---

## 3. Flujo de una pregunta del usuario (chat con RAG)

```mermaid
sequenceDiagram
    actor U as Usuario
    participant W as Widget (Preact)
    participant API as Backend /api/v1/chat
    participant G as Guardrails
    participant RL as Rate Limiter (Redis)
    participant SC as Semantic Cache
    participant R as Adaptive RAG Router
    participant Q as Qdrant
    participant L as LLM (Groq/OpenAI/etc)
    participant DB as MySQL

    U->>W: escribe pregunta
    W->>API: POST /chat (SSE)

    API->>G: validar input (4000 chars, anti-inyección, PII)
    alt Inyección detectada
        G-->>API: bloqueado
        API-->>W: error: "petición bloqueada"
    end

    API->>RL: check IP rate limit
    alt Rate exceeded
        RL-->>API: 429
        API-->>W: error: "demasiadas peticiones"
    end

    API->>SC: ¿hit cache semántico?
    alt Hit (similarity ≥ 0.93)
        SC-->>API: respuesta cacheada
        API-->>W: SSE: sources + token + done
    else Miss
        API->>R: classify_query()
        alt Greeting
            R-->>API: respuesta predefinida
            API-->>W: SSE: token + done
        else Factual o Complex
            R->>Q: hybrid_search (dense + BM25 RRF)
            Q-->>R: top_k chunks
            opt CRAG (complex)
                R->>L: grade_documents
                L-->>R: relevantes
            end
            R->>L: stream_chat (con parent_text)
            loop tokens
                L-->>R: token
                R-->>API: token
                API-->>W: SSE: token
            end
        end

        API->>DB: persist conversación + mensajes
        API->>SC: store(question, answer)
        API-->>W: SSE: done (latency, route, model)
    end

    W-->>U: muestra respuesta token a token
```

**Estados del request**:

- 1-4: validación de input (< 50 ms).
- 5: cache semántico (hit ratio esperado 30-60% post-warmup).
- 6-7: clasificación de la query y retrieval (200-800 ms).
- 8: streaming del LLM (1-30 s según modelo).

---

## 4. Pipeline de ingestión de fuentes

```mermaid
flowchart TB
    upload["Admin sube fuente<br/>(PDF / DOCX / XLSX / CSV / TXT / FAQ)"]
    detect{"Tipo?"}

    upload --> detect
    detect -->|PDF| ext_pdf["pypdf"]
    detect -->|DOCX| ext_docx["python-docx"]
    detect -->|XLSX/CSV| ext_sheet["openpyxl / csv"]
    detect -->|TXT| ext_txt["texto plano"]
    detect -->|FAQ| faq["Texto directo<br/>(sin archivo)"]

    ext_pdf --> chunk
    ext_docx --> chunk
    ext_sheet --> chunk
    ext_txt --> chunk
    faq --> chunk

    chunk["Parent-Child chunking<br/>hijos 1024 chars<br/>padres 4000 chars"]

    chunk --> warn["Detectar warnings<br/>(short, long, PII, dup)"]
    warn --> embed["Embeddings<br/>(e5-large + BM25)"]
    embed --> upsert["Upsert en Qdrant<br/>con payload"]
    upsert --> review["Status:<br/>pendiente_revision"]
    review --> admin{"Admin?"}
    admin -->|Aprobar| ready["Status: aprobada<br/>visible al chatbot"]
    admin -->|Rechazar| rejected["Status: rechazada<br/>oculta"]

    classDef approved fill:#1FB107,stroke:#1FB107,color:#fff
    classDef rejected fill:#dc2626,stroke:#dc2626,color:#fff
    classDef pending fill:#f59e0b,stroke:#f59e0b,color:#fff

    class ready approved
    class rejected rejected
    class review pending
```

**Tiempos típicos** (fuente de 30 páginas PDF):

- Extracción: 2-5 s.
- Chunking: < 1 s (~500 chunks hijos).
- Embeddings: 8-15 s (CPU only).
- Upsert Qdrant: < 2 s.

**Nota sobre aprobación**: los documentos (PDF/DOCX/XLSX/CSV/TXT) quedan en estado `pendiente_revision` hasta que un admin los aprueba. Las FAQs creadas desde el panel se aprueban automáticamente.

---

## 5. Modelo de datos (resumen)

```mermaid
erDiagram
    USERS ||--o{ SOURCES : "subió"
    USERS ||--o{ AUDIT_LOGS : "actor"

    SOURCES ||--o{ CHUNK_EDITS : "tiene"
    SOURCES ||--o{ FAQ_ENTRIES : "FAQ asociada"

    CHAT_CONVERSATIONS ||--o{ CHAT_MESSAGES : "incluye"
    CHAT_CONVERSATIONS ||--o{ UNANSWERED_QUESTIONS : "marca"

    USERS {
        uuid id PK
        string email UK
        string role "rol dinámico (admin/editor/viewer/...)"
        bool is_active
        bool must_change_password
        timestamp last_login_at
        timestamp tokens_valid_after "invalidación de sesiones"
    }

    SOURCES {
        uuid id PK
        string name
        string type "pdf/docx/xlsx/csv/txt/faq"
        string status "pending/processing/ready/error"
        string review_status "procesando/pendiente_revision/aprobada/rechazada"
        int chunk_count
        json meta
    }

    CHAT_CONVERSATIONS {
        uuid id PK
        string session_id
        string status "active/resolved/escalated/in_attention/abandoned"
        bool escalation_pending
        timestamp last_message_at
    }

    CHAT_MESSAGES {
        uuid id PK
        uuid conversation_id FK
        string role "user/assistant"
        text content
        json sources_json
        int latency_ms
        string rag_route
    }

```

---

## 6. Adaptive RAG — máquina de estados

```mermaid
stateDiagram-v2
    [*] --> Classify

    Classify --> Greeting: query es saludo
    Classify --> Factual: query corta, factual
    Classify --> Complex: query elaborada

    Greeting --> [*]: respuesta predefinida<br/>(sin retrieval)

    Factual --> Retrieve: hybrid search
    Retrieve --> Rerank: reranker activo?
    Rerank --> [*]: top_k chunks
    Retrieve --> [*]: top_k chunks (sin rerank)

    Complex --> Expand: rewrite_query
    Expand --> Retrieve2: hybrid search
    Retrieve2 --> Grade: grade_documents (LLM)
    Grade --> [*]: relevantes>0
    Grade --> Rewrite: relevantes=0 && rewrites<1
    Rewrite --> Retrieve2
    Grade --> [*]: rewrites=1 (devuelve todos)
```

**Ahorro de tokens**:

- Greeting: 0 llamadas LLM, 0 retrievals.
- Factual: 1 llamada LLM (generación), 1 retrieval.
- Complex: 2-3 llamadas LLM (grade + opcional rewrite + generación).

---

## 7. Layout del repositorio

```text
chatbot-uso-v2/
├── backend/                FastAPI + SQLAlchemy + Alembic
│   ├── app/
│   │   ├── api/v1/         Endpoints (auth, sources, chat, analytics, ...)
│   │   ├── core/           config, security, deps, rate_limit, redis
│   │   ├── db/             session async
│   │   ├── models/         SQLAlchemy ORM
│   │   ├── schemas/        Pydantic
│   │   └── services/       Lógica de negocio
│   │       ├── chat/       pipeline.py (SSE + cache + scope)
│   │       ├── rag/        Adaptive RAG (corrective.py + router.py)
│   │       ├── ingestion/  chunking, embedding, vector_store
│   │       ├── knowledge/  faq.py
│   │       └── ai/         guardrails.py, semantic_cache.py, embedding.py
│   ├── alembic/versions/   Migraciones
│   └── tests/              pytest
│
├── frontend/               Next.js 15 + Tailwind v4
│   └── src/
│       ├── app/(dashboard)/    Páginas del panel
│       │   └── dashboard/
│       │       ├── configuracion/  Toda la administración, expuesta en el
│       │       │                   sidebar como grupos plegables: Chatbot,
│       │       │                   Sistema y Acceso
│       │       ├── conocimiento/   Gestión KB (documentos + FAQ)
│       │       ├── estadisticas/   Métricas y analytics
│       │       ├── reportes/       Reportes descargables en PDF
│       │       ├── conversaciones/ Historial y escalamientos
│       │       └── actividad/      Auditoría y seguridad
│       ├── components/             UI (shadcn)
│       └── hooks/, types/, lib/
│
└── widget/                 SDK Preact embebible (Shadow DOM)
```

---

## 8. Seguridad

| Mecanismo | Implementación |
| --- | --- |
| Autenticación | JWT (access + refresh) con rotación de refresh y detección de reuso |
| Invalidación de sesiones | Denylist de `jti` en Redis (logout) + `tokens_valid_after` por usuario (cambio de contraseña) |
| Autorización | RBAC dinámico en BD: roles y permisos `(módulo, acción)` configurables desde el panel |
| Contraseñas | bcrypt |
| Secretos en reposo | Cifrado Fernet (API keys de proveedores) con derivación PBKDF2-HMAC-SHA256 |
| Anti–fuerza bruta | Rate limit por IP en endpoints de auth (Redis, con fallback en memoria) |
| Guardrails de entrada | Detección de inyección de prompts por regex (built-in + personalizables) |
| Redacción de PII | Presidio en español: email, teléfono, tarjeta, IBAN + documentos de El Salvador (DUI, NIT, NRC) |
| Rate limiting del chat | Multidimensional: por IP/minuto, por IP/hora y por sesión |
| Widget público | Validación de API key + allowlist de dominios por `Origin` |
| IP real tras proxy | `CF-Connecting-IP` / `X-Real-IP` / `X-Forwarded-For` |

## 9. Notificaciones por correo

El sistema envía correo (SMTP, configurado por variables de entorno) en:

- **Invitaciones de usuario**: enlace de registro al correo del invitado.
- **Escalamientos**: aviso a los administradores cuando una conversación se escala.
- **Reglas de notificación**: eventos configurables (servicio caído, proveedor caído, etc.).

El envío es *best-effort*: un fallo de SMTP queda registrado pero no interrumpe la operación que lo originó.

## 10. Convención de configuración: fuente única

Cada ajuste tiene exactamente una fuente:

- **`.env`**: infraestructura y secretos (BD, Redis, Qdrant, SECRET_KEY, SMTP,
  OAuth, CORS, límites de auth) y la segmentación de documentos
  (`CHATBOT_CHUNK_*`, porque cambiarla exige reingestar).
- **Base de datos (panel)**: todo el comportamiento operable, con defaults en
  el código: parámetros del asistente, mensajes, cuotas del chat y caché
  semántico. El `.env` no participa en estos valores.

## 11. Convenciones de la interfaz

- El texto del panel de administración, los errores de la API y los correos emplea tratamiento formal de **usted**.
- El chatbot público y el widget **tutean** a propósito (el system prompt por defecto instruye "tutea al usuario") — es una decisión de producto para el público estudiantil.
- No se exponen detalles técnicos de configuración (rutas, variables de entorno, logs) en la interfaz.
- La terminología es en español: las acciones de valoración (👍/👎) se denominan «valoración», no «feedback».

## 12. Versionado de configuración

El sistema mantiene un historial de versiones de toda la configuración
(proveedores, asistente, widget, escalamiento, notificaciones, fuentes, FAQ)
como snapshots JSON en la tabla `config_versions`.

Las versiones se generan de tres formas:

- **Automática**: un middleware ASGI captura un snapshot tras cada mutación
  exitosa de configuración (sin añadir latencia a la respuesta — es
  *fire-and-forget*). Solo crea una versión nueva si hubo cambios reales
  respecto a la anterior.
- **Manual**: el administrador crea un punto de restauración explícito.
- **En despliegue**: al publicar a producción.

Los secretos (contraseñas SMTP, credenciales OAuth) se enmascaran en los
snapshots. Cualquier versión puede restaurarse (rollback).
