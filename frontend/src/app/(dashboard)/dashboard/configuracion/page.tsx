import { redirect } from "next/navigation";

// /dashboard/configuracion es una sección landing - siempre envía al usuario
// a la primera subruta canónica para que recargar, el historial y los
// marcadores se mantengan consistentes.
export default function ConfiguracionRoot() {
  redirect("/dashboard/configuracion/asistente");
}
