import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { Search } from "lucide-react";

export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="max-w-sm text-center space-y-4">
        <div className="mx-auto w-12 h-12 rounded-full bg-muted flex items-center justify-center">
          <Search className="w-6 h-6 text-muted-foreground" />
        </div>
        <h1 className="text-xl font-semibold text-foreground">
          Página no encontrada
        </h1>
        <p className="text-sm text-muted-foreground">
          La página que buscas no existe o fue movida.
        </p>
        <Link href="/dashboard" className={buttonVariants()}>
          Ir al inicio
        </Link>
      </div>
    </div>
  );
}
