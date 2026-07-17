"use client";

import { ShieldCheck } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";

export default function AccesoLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <PageHeader
        icon={ShieldCheck}
        title="Gestión de acceso"
        tip="Administre usuarios e inicio de sesión del panel."
      />
      {children}
    </div>
  );
}
