import { redirect } from "next/navigation";

// /dashboard/configuracion is a section landing — always send the user to the
// canonical first sub-route so reload, history, and bookmarks stay clean.
export default function ConfiguracionRoot() {
 redirect("/dashboard/configuracion/asistente");
}
