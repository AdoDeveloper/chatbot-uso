import { redirect } from "next/navigation";

export default function AuditoriaPage() {
  redirect("/dashboard/actividad?tab=auditoria");
}
