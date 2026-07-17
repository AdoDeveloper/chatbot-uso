// UserRole ya no es un enum fijo — los roles son dinámicos.
// Se mantiene el alias para compatibilidad con el código existente.
export type UserRole = string;

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;      // nombre del rol dinámico
  is_active: boolean;
  must_change_password: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export type SourceType = "pdf" | "docx" | "xlsx" | "csv" | "txt" | "faq";
export type SourceStatus = "pending" | "processing" | "ready" | "error";
export type ReviewStatus = "procesando" | "pendiente_revision" | "aprobada" | "rechazada";

export interface SourcePreview {
  preview: string;
  truncated: boolean;
  error?: string;
}

export interface SourceQuality {
  source_id: string;
  name: string;
  total_chunks: number;
  last_used_at: string | null;
  hits_7d: number;
  review_status: string;
}

export interface Source {
  id: string;
  name: string;
  description: string | null;
  type: SourceType;
  status: SourceStatus;
  review_status: ReviewStatus;
  reviewed_at: string | null;
  reviewed_by_name: string | null;
  rejection_reason: string | null;
  file_size: number | null;
  chunk_count: number;
  error_message: string | null;
  error_code: string | null;
  error_hint: string | null;
  progress_stage: string | null;
  meta: Record<string, unknown>;
  tags: string[];
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface LLMProvider {
  id: string;
  name: string;
  provider_type: string;
  model_name: string;
  api_base: string | null;
  dashboard_url: string | null;
  has_api_key: boolean;
  is_active: boolean;
  priority: number | null;
  created_at: string;
  updated_at: string;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_test_latency_ms: number | null;
  last_test_error: string | null;
}

export interface ChatbotSettings {
  chatbot_name: string;
  welcome_message: string;
  system_prompt: string;
  top_k: number;
  score_threshold: number;
  temperature: number;
  max_tokens: number;
  use_corrective_rag: boolean;
  use_reranker: boolean;
  greeting_response: string;
  no_providers_message: string;
  guardrail_blocked_message: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: UserRole;
  token: string;
  created_by_id: string | null;
  expires_at: string;
  accepted_at: string | null;
  is_active: boolean;
  created_at: string;
  invite_url: string | null;
}

export type ConversationStatus = "active" | "escalated" | "resolved";
export type MessageRole = "user" | "assistant";
export type MessageFeedback = "positive" | "negative";

export interface ChatMessageOut {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  sources_json: Array<{ source_name: string; score: number; content: string }>;
  latency_ms: number | null;
  rag_route: string | null;
  feedback: MessageFeedback | null;
  created_at: string;
}

export interface ChatConversationOut {
  id: string;
  session_id: string;
  user_id: string | null;
  status: ConversationStatus;
  device: string | null;
  browser: string | null;
  origin_url: string | null;
  started_at: string;
  last_message_at: string;
  escalated_at: string | null;
  assigned_to_user_id: string | null;
  assigned_at: string | null;
  resolved_at: string | null;
  resolved_by_user_id: string | null;
  csat_score: number | null;
  escalation_trigger_reason: string | null;
  tags: string[];
  message_count: number;
  first_user_message: string | null;
}

export interface ConversationTag {
  tag: string;
  count: number;
}

export interface RootCause {
  question_id: string;
  detected_topic: string | null;
  causes: { code: string; label: string; detail: string }[];
  suggestions: string[];
}

export interface ChatConversationDetail extends ChatConversationOut {
  messages: ChatMessageOut[];
}

export interface AnalyticsDashboard {
  queries_today: number;
  queries_today_delta: number;
  queries_yesterday: number;
  queries_week: number;
  resolution_rate: number;
  resolution_rate_delta: number;
  unique_users_today: number;
  avg_latency_ms: number;        // P50
  avg_latency_delta: number;
  p95_latency_ms: number;        // P95
  active_sources: number;
  unanswered_pending: number;
}

export interface PeriodSnapshot {
  range_start: string;
  range_end: string;
  queries: number;
  unique_sessions: number;
  resolution_rate: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
}

export interface PeriodComparison {
  current: PeriodSnapshot;
  previous: PeriodSnapshot;
  deltas: Record<string, number>;
}

export interface ChannelStat {
  channel: string;
  count: number;
  percentage: number;
}

export interface CacheStats {
  hits: number;
  misses: number;
  hit_rate: number;
  days: number;
}

export interface PageStat {
  page: string;
  count: number;
  percentage: number;
}

export interface TopicStat {
  topic: string;
  count: number;
  resolution_rate: number;
}

export interface HeatmapCell {
  hour?: number | null;
  day?: number | null;
  date?: string | null;
  count: number;
}

export type HeatmapWindow = "day" | "week" | "month" | "year";

export interface TimeSeriesPoint {
  date: string;
  count: number;
}

export type UnansweredStatus = "open" | "in_progress" | "resolved";

export interface UnansweredQuestion {
  id: string;
  conversation_id: string | null;
  question: string;
  detected_topic: string | null;
  status: UnansweredStatus;
  created_at: string;
}

export interface UnansweredGroup {
  topic: string;
  count: number;
  first_seen: string;
  last_seen: string;
  questions: UnansweredQuestion[];
}

export interface FAQEntry {
  id: string;
  question: string;
  answer: string;
  tags: string[];
  is_active: boolean;
  source_id: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuditLog {
  id: string;
  actor_id: string | null;
  actor_name: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  meta_json: Record<string, unknown>;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
}

export type NotificationEvent =
  | "doc_ready"
  | "doc_error"
  | "escalation"
  | "provider_down"
  | "unanswered_daily"
  | "rate_limit_threshold"
  | "service_down";

export type NotificationChannel = "email";

export interface NotificationRule {
  id: string;
  event: NotificationEvent;
  channel: NotificationChannel;
  enabled: boolean;
  target: string | null;
  config_json: Record<string, unknown>;
  updated_at: string;
}

export type EscalationTrigger =
  | "no_answer"
  | "user_request"
  | "negative_feedback"
  | "keyword_detected"
  | "confidence_below"
  | "loop_detected";

export interface RuleTestResult {
  matches: boolean;
  detail: string;
  trigger_type: EscalationTrigger;
  payload_preview: Record<string, unknown>;
}

export interface EscalationRule {
  id: string;
  name: string;
  description: string;
  trigger_type: EscalationTrigger;
  trigger_config: Record<string, unknown>;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface WidgetConfig {
  id: string;
  api_key: string;
  chatbot_name: string;
  welcome_message: string;
  primary_color: string;
  position: string;
  logo_url: string | null;
  domain_allowlist: string[];
  show_sources: boolean;
  enable_copy_action: boolean;
  enable_feedback_icons: boolean;
  // Botón de lectura en voz alta (TTS) junto a cada respuesta del bot.
  enable_tts: boolean;
  // Master switch del menú de accesibilidad (tamaño de texto + alto
  // contraste + TTS) en el kebab. Independiente de enable_tts.
  enable_accessibility: boolean;
  // Si es false, el header del widget y las burbujas del bot no muestran el
  // icono SVG. Default true (cuando no viene del backend).
  show_bot_icon: boolean;
  // Quick replies que aparecen sobre el input solo en el welcome. Vacio = no
  // se muestran. Maximo 6, validado en backend.
  suggestions: string[];
  // Mensaje proactivo flotante sobre el launcher cerrado. "" = desactivado.
  proactive_message: string;
  max_chats_per_session: number | null;
  max_chats_per_day: number | null;
  show_end_chat_button: boolean;
  show_new_chat_button: boolean;
  enable_csat: boolean;
  csat_question: string;
  // Master switch del escalamiento a humano. Si es false, el bot nunca ofrece
  // "hablar con un humano" ni evalua reglas de escalamiento.
  enable_escalation: boolean;
  launcher_label: string;
  updated_at: string;
}

export interface ServiceStatus {
  name: string;
  status: string;
  latency_ms: number | null;
  detail: string | null;
}

export interface ComputeDevice {
  embedding: string;
  reranker: string;
  gpu_available: boolean;
}

export interface HealthDetailed {
  status: string;
  services: ServiceStatus[];
  version: string;
  environment: string;
  compute?: ComputeDevice;
}

export interface HealthSnapshotRow {
  service_name: string;
  is_ok: boolean;
  latency_ms: number | null;
  recorded_at: string;
  cpu_percent: number | null;
  mem_percent: number | null;
  disk_percent: number | null;
}

export interface UptimeRow {
  service_name: string;
  uptime_pct: number;
  samples: number;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
  last_ok: boolean | null;
  last_latency_ms: number | null;
  last_recorded_at: string | null;
}

export interface HealthIncident {
  service_name: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  samples: number;
  last_error: string | null;
}

export interface Role {
  name: string;
  display_name: string;
  description: string | null;
  is_system: boolean;
  created_at: string;
}
