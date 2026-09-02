import { redirect } from "next/navigation";

// Redirige a la pestaña de apariencia dentro de Configuración > Asistente.
export default function WidgetPage() {
 redirect("/dashboard/configuracion/asistente?tab=apariencia");
}
