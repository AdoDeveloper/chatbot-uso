import { useCallback } from "react";
import { useAuth } from "@/contexts/auth-context";
import type { PermissionKey } from "@/lib/permissions";

export function usePermission() {
  const { permissions } = useAuth();
  return useCallback(
    (permission: PermissionKey | string): boolean =>
      permissions.has("*") || permissions.has(permission),
    [permissions],
  );
}
