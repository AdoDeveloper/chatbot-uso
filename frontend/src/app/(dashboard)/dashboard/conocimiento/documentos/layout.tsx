import { Database } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { DocumentosTabs } from "./_components/DocumentosTabs";

export default function DocumentosLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <PageHeader
        icon={Database}
        title="Documentos"
        tip="Fuentes de datos y FAQ que alimentan al chatbot."
      />
      <DocumentosTabs />
      {children}
    </div>
  );
}
