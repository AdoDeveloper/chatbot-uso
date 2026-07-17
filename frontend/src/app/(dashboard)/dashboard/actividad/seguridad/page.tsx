import { redirect } from "next/navigation";

export default function SeguridadPage() {
  redirect("/dashboard/actividad?tab=seguridad");
}
