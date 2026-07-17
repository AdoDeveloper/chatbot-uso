import { redirect } from "next/navigation";

export default function InyeccionesPage() {
  redirect("/dashboard/actividad?tab=inyecciones");
}
