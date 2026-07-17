"use client";

import type { ChatbotSettings } from "@/types";
import { Switch } from "@/components/ui/switch";
import { ParamField } from "@/components/ui/param-field";
import { Input } from "@/components/ui/input";

const RAG_PRESETS = [
 {
  id: "preciso",
  label: "Preciso",
  description: "Respuestas fieles al documento, sin divagaciones",
  values: { top_k: 5, score_threshold: 0.3, temperature: 0.1, use_corrective_rag: true, use_reranker: true },
 },
 {
  id: "equilibrado",
  label: "Equilibrado",
  description: "Balance entre precisión y fluidez (recomendado)",
  values: { top_k: 8, score_threshold: 0.0, temperature: 0.3, use_corrective_rag: true, use_reranker: false },
 },
 {
  id: "exploratorio",
  label: "Exploratorio",
  description: "Respuestas amplias con más contexto",
  values: { top_k: 12, score_threshold: 0.0, temperature: 0.6, use_corrective_rag: true, use_reranker: false },
 },
] as const;

type RagPresetId = (typeof RAG_PRESETS)[number]["id"];

function detectActivePreset(form: ChatbotSettings): RagPresetId | null {
 for (const p of RAG_PRESETS) {
  if (
   form.top_k === p.values.top_k &&
   form.score_threshold === p.values.score_threshold &&
   form.temperature === p.values.temperature &&
   form.use_corrective_rag === p.values.use_corrective_rag &&
   form.use_reranker === p.values.use_reranker
  ) return p.id;
 }
 return null;
}

export function ParamsTab({ form, set }: { form: ChatbotSettings; set: (k: keyof ChatbotSettings, v: unknown) => void }) {
 const activePreset = detectActivePreset(form);

 function applyPreset(id: RagPresetId) {
  const preset = RAG_PRESETS.find((p) => p.id === id);
  if (!preset) return;
  Object.entries(preset.values).forEach(([k, v]) => set(k as keyof ChatbotSettings, v));
 }

 return (
  <div className="space-y-6">
   {/* ── Presets rápidos ──────────────────────────────────────────────── */}
   <div className="bg-card border border-border rounded-xl shadow-sm p-6 space-y-3">
    <div>
     <h3 className="text-15 font-semibold tracking-tight">Perfil del asistente</h3>
     <p className="text-2xs text-muted-foreground mt-1">Configura todos los parámetros RAG de una vez. Los sliders debajo siguen disponibles para ajuste fino.</p>
    </div>
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
     {RAG_PRESETS.map((p) => {
      const active = activePreset === p.id;
      return (
       <button
        key={p.id}
        type="button"
        onClick={() => applyPreset(p.id)}
        className={`flex flex-col items-start gap-1 rounded-xl border p-3.5 text-left transition-all ${
         active
          ? "border-primary bg-primary/5 ring-1 ring-primary/20"
          : "border-border hover:border-primary/40 hover:bg-muted/30"
        }`}
       >
        <span className={`text-sm font-semibold ${active ? "text-primary" : "text-foreground"}`}>{p.label}</span>
        <span className="text-2xs text-muted-foreground leading-snug">{p.description}</span>
        {active && <span className="text-3xs text-primary font-medium mt-0.5">● Activo</span>}
       </button>
      );
     })}
    </div>
   </div>

   <div className="bg-card border border-border rounded-xl shadow-sm p-6 space-y-5">
    <h3 className="text-15 font-semibold tracking-tight">Recuperación</h3>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
     <ParamField
      label="Fragmentos recuperados"
      valueBadge={form.top_k}
      help={{
       description: "Cuántos fragmentos de texto se recuperan de la base de conocimiento y se pasan al modelo como contexto para generar la respuesta.",
       example: "Valores entre 5 y 10 suelen ser óptimos. Más fragmentos = más contexto pero respuestas más lentas y caras.",
      }}
     >
      <input type="range" min={1} max={20} step={1} value={form.top_k}
       onChange={(e) => set("top_k", Number(e.target.value))} className="w-full accent-primary" />
     </ParamField>
     <ParamField
      label="Umbral de relevancia"
      valueBadge={form.score_threshold.toFixed(2)}
      help={{
       description: "Puntaje mínimo que debe tener un fragmento para incluirse. Se mide entre 0 (cualquier cosa) y 1 (coincidencia perfecta).",
       example: "0 = sin filtro. 0.3–0.5 = equilibrio. Si sube a 0.7+ el chatbot puede quedarse sin contexto y responder 'no sé'.",
      }}
     >
      <input type="range" min={0} max={1} step={0.05} value={form.score_threshold}
       onChange={(e) => set("score_threshold", Number(e.target.value))} className="w-full accent-primary" />
     </ParamField>
    </div>
    <div className="flex items-center justify-between gap-3 py-3 border-t border-border">
     <div className="flex items-center gap-1.5 min-w-0">
      <div className="min-w-0">
       <p className="text-13 font-medium text-foreground">Revisión de relevancia</p>
       <p className="text-2xs text-muted-foreground mt-0.5">Evalúa si los documentos recuperados son relevantes y reformula la consulta si es necesario.</p>
      </div>
     </div>
     <Switch checked={form.use_corrective_rag} onCheckedChange={(v) => set("use_corrective_rag", v)} className="shrink-0" />
    </div>
    <div className="flex items-center justify-between gap-3 py-3 border-t border-border">
     <div className="min-w-0">
      <p className="text-13 font-medium text-foreground">Reordenamiento por relevancia</p>
      <p className="text-2xs text-muted-foreground mt-0.5">Reordena los fragmentos recuperados para priorizar los más relevantes. Mejora la precisión de las respuestas añadiendo ~350ms.</p>
     </div>
     <Switch checked={form.use_reranker} onCheckedChange={(v) => set("use_reranker", v)} className="shrink-0" />
    </div>
   </div>
   <div className="bg-card border border-border rounded-xl shadow-sm p-6 space-y-5">
    <h3 className="text-15 font-semibold tracking-tight">Generación de respuesta</h3>
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-6">
     <ParamField
      label="Temperatura"
      valueBadge={form.temperature.toFixed(2)}
      hint="Más bajo = preciso · Más alto = creativo"
      help={{
       description: "Controla la aleatoriedad del modelo. Un valor bajo hace que responda siempre parecido a la misma pregunta; un valor alto lo hace más creativo pero menos consistente.",
       example: "Para FAQs y soporte: 0.1–0.3. Para generación creativa: 0.7–1.0.",
      }}
     >
      <input type="range" min={0} max={2} step={0.05} value={form.temperature}
       onChange={(e) => set("temperature", Number(e.target.value))} className="w-full accent-primary" />
     </ParamField>
     <ParamField
      label="Longitud máxima de respuesta"
      help={{
       description: "Longitud máxima de la respuesta que puede generar el modelo. 1 unidad ≈ 0.75 palabras en español.",
       example: "1024 ≈ 700 palabras. Si el valor es muy alto, las respuestas pueden quedar innecesariamente largas.",
      }}
     >
      <Input type="number" min={64} max={8192} step={64} value={form.max_tokens}
       onChange={(e) => set("max_tokens", Number(e.target.value))} />
     </ParamField>
    </div>
   </div>
  </div>
 );
}
