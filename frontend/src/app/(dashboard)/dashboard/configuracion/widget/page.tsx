import { redirect } from "next/navigation";

// "Widget" se fusionó dentro de Asistente (Identidad y apariencia /
// Integración / Límites) — un solo lugar para todo lo que define al
// chatbot, con un único preview funcional en vez de dos.
export default function WidgetPage() {
 redirect("/dashboard/configuracion/asistente?tab=apariencia");
}
