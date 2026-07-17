"use client";

import { Zap } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { ProvidersTab, UnpublishedBanner } from "../_lib/tabs";

export default function ProveedoresPage() {
 return (
  <div>
   <UnpublishedBanner />
   <PageHeader icon={Zap} title="Proveedores LLM" tip="Modelos y claves de API que el chatbot puede usar." />
   <ProvidersTab />
  </div>
 );
}
