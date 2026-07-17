"use client";

import type { ChatbotSettings } from "@/types";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { CollapsibleCard } from "./shared";

export function PromptTab({ form, set }: { form: ChatbotSettings; set: (k: keyof ChatbotSettings, v: unknown) => void }) {
 return (
  <div className="space-y-5">
   <div className="bg-card border border-border rounded-xl shadow-sm p-6 space-y-5">
    <div>
     <h3 className="text-15 font-semibold tracking-tight">Identidad del asistente</h3>
     <p className="text-2xs text-muted-foreground mt-1">Cómo se presenta el bot a los usuarios finales.</p>
    </div>
    <div>
     <label className="block text-xs font-medium text-muted-foreground mb-1.5">Nombre</label>
     <Input value={form.chatbot_name} onChange={(e) => set("chatbot_name", e.target.value)} />
    </div>
    <div>
     <label className="block text-xs font-medium text-muted-foreground mb-1.5">Mensaje de bienvenida</label>
     <Input value={form.welcome_message} onChange={(e) => set("welcome_message", e.target.value)} />
    </div>
   </div>
   <CollapsibleCard
    title="Prompt del sistema"
    description={<>Instrucciones base del modelo. Usa <code className="text-xs bg-muted px-1 rounded">{"{context}"}</code> para insertar las fuentes recuperadas.</>}
    preview={form.system_prompt.split("\n").slice(0, 2).join(" · ").slice(0, 140) + (form.system_prompt.length > 140 ? "…" : "")}
   >
    <Textarea value={form.system_prompt} onChange={(e) => set("system_prompt", e.target.value)}
     rows={14}
     className="font-mono resize-none leading-relaxed" />
   </CollapsibleCard>

   <CollapsibleCard
    title="Mensajes automáticos"
    description="Respuestas automáticas del bot: saludo cuando el usuario solo dice 'hola', error cuando no hay servicio de IA disponible, y bloqueo cuando los filtros detectan contenido no permitido."
   >
    <div className="space-y-5 pt-2">
     <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1.5">
       Saludo automático
      </label>
      <p className="text-2xs text-muted-foreground mb-2">
       Se devuelve cuando la entrada es solo un saludo (&ldquo;hola&rdquo;, &ldquo;buenos días&rdquo;, &ldquo;gracias&rdquo;…). Sin invocar al LLM.
      </p>
      <Textarea
       value={form.greeting_response}
       onChange={(e) => set("greeting_response", e.target.value)}
       rows={3}
       maxLength={500}
       className="resize-none"
      />
      <p className="text-2xs text-muted-foreground mt-1 text-right">
       {form.greeting_response.length}/500
      </p>
     </div>

     <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1.5">
       Bloqueo por guardrails
      </label>
      <p className="text-2xs text-muted-foreground mb-2">
       Se devuelve cuando los filtros de seguridad detectan contenido no permitido. Mantenelo amable y reorienta la conversación.
      </p>
      <Textarea
       value={form.guardrail_blocked_message}
       onChange={(e) => set("guardrail_blocked_message", e.target.value)}
       rows={2}
       maxLength={300}
       className="resize-none"
      />
      <p className="text-2xs text-muted-foreground mt-1 text-right">
       {form.guardrail_blocked_message.length}/300
      </p>
     </div>

     <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1.5">
       Sin servicio de IA disponible
      </label>
      <p className="text-2xs text-muted-foreground mb-2">
       Mensaje que verá el usuario cuando ningún proveedor de IA esté activo o configurado.
      </p>
      <Textarea
       value={form.no_providers_message}
       onChange={(e) => set("no_providers_message", e.target.value)}
       rows={2}
       maxLength={300}
       className="resize-none"
      />
      <p className="text-2xs text-muted-foreground mt-1 text-right">
       {form.no_providers_message.length}/300
      </p>
     </div>
    </div>
   </CollapsibleCard>
  </div>
 );
}
