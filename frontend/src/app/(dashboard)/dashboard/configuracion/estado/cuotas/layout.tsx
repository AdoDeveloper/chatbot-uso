import { CuotasTabs } from "./_components/CuotasTabs";

export default function CuotasLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-base font-semibold flex-1 min-w-0 truncate">Cuotas de uso</h2>
      </div>
      <CuotasTabs />
      {children}
    </div>
  );
}
