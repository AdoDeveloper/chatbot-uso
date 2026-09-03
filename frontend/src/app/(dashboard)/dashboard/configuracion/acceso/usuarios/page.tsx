"use client";

import { useEffect, useState } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import api from "@/lib/api";
import type { User, Invitation, Role } from "@/types";
import { useAuth } from "@/contexts/auth-context";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { timeAgo } from "@/lib/utils";
import { usePermission } from "@/hooks/use-permission";
import { PERM } from "@/lib/permissions";
import { useToast } from "@/components/ui/toast";
import {
  Users, UserPlus, Pencil, Trash2, ShieldCheck, CheckCircle, Clock,
  Copy, XCircle, AlertCircle, Check, X, Save, Loader2, Send, KeyRound, RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Modal } from "@/components/composed/modal";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Select, SelectOption } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { TableCell, TableRow } from "@/components/ui/table";
import { StatCard } from "@/components/composed/stat-card";
import { Badge } from "@/components/ui/badge";
import { DataTable } from "@/components/composed/data-table";
import { formatInProjectTz } from "@/lib/datetime";

const ROLE_BADGE: Record<string, string> = {
  admin:  "bg-primary/10 text-primary",
  editor: "bg-brand-green/10 text-brand-green",
  viewer: "bg-muted text-muted-foreground",
};

function roleBadgeClass(name: string) {
  return ROLE_BADGE[name] ?? "bg-muted text-muted-foreground";
}

function fmtDate(iso: string | null) {
  if (!iso) return "Nunca";
  return formatInProjectTz(iso, {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function buildInviteUrl(token: string) {
  if (typeof window === "undefined") return `/invite/${token}`;
  return `${window.location.origin}/invite/${token}`;
}

type InviteStatus = "active" | "expired" | "accepted" | "revoked";

function inviteStatus(inv: Invitation): InviteStatus {
  if (inv.accepted_at) return "accepted";
  if (!inv.is_active) return "revoked";
  if (new Date(inv.expires_at) < new Date()) return "expired";
  return "active";
}

const INVITE_STATUS_META: Record<InviteStatus, { label: string; className: string }> = {
  active: { label: "Activa", className: "bg-success/10 text-success" },
  expired: { label: "Expirada", className: "bg-warning/10 text-warning" },
  accepted: { label: "Aceptada", className: "bg-primary/10 text-primary" },
  revoked: { label: "Revocada", className: "bg-muted text-muted-foreground" },
};

function UserAvatar({ name, email }: { name: string; email: string }) {
  const initials = name.split(" ").slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("");
  const colors = [
    "bg-primary/15 text-primary", "bg-brand-green/15 text-brand-green",
    "bg-brand-teal/15 text-brand-teal", "bg-warning/15 text-warning", "bg-brand-cornflower/20 text-brand-steel",
  ];
  return (
    <div className={`w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold shrink-0 ${colors[email.charCodeAt(0) % colors.length]}`}>
      {initials || "?"}
    </div>
  );
}

const editUserSchema = z.object({
  fullName: z.string().min(1, "El nombre no puede estar vacío"),
  role: z.string(),
  isActive: z.boolean(),
});

function EditUserPanel({ user, meId, availableRoles, onClose, onSaved }: {
  user: User | null; meId: string | undefined;
  availableRoles: Role[]; onClose: () => void; onSaved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const isSelf = !!user && user.id === meId;
  const { toast } = useToast();

  const { register, handleSubmit, reset, watch, setValue, formState: { errors, isSubmitting } } = useForm<z.infer<typeof editUserSchema>>({
    resolver: zodResolver(editUserSchema),
    defaultValues: {
      fullName: user?.full_name ?? "",
      role: user?.role ?? "viewer",
      isActive: user?.is_active ?? true,
    },
  });

  useEffect(() => {
    if (user) reset({ fullName: user.full_name, role: user.role, isActive: user.is_active });
  }, [user?.id, reset]);

  const onSubmit = handleSubmit(async (data) => {
    if (!user) return;
    setError(null);
    try {
      const body: Record<string, unknown> = { full_name: data.fullName.trim() };
      if (!isSelf) { body.role = data.role; body.is_active = data.isActive; }
      await api.patch(`/users/${user.id}`, body);
      toast({ type: "success", message: "Usuario actualizado." });
      onSaved(); onClose();
    } catch (err: unknown) {
      setError(getErrorMessage(err, "No se pudo actualizar"));
    }
  });

  const roles = availableRoles;

  return (
    <Modal
      open={!!user}
      onClose={onClose}
      title="Editar usuario"
      size="lg"
      onSubmit={onSubmit}
      footer={
        <div className="flex gap-3 w-full">
          <Button variant="outline" className="flex-1 gap-1.5" onClick={onClose} type="button"><X className="w-3.5 h-3.5" /> Cancelar</Button>
          <Button className="flex-1 gap-1.5" type="submit" disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            {isSubmitting ? "Guardando..." : "Guardar"}
          </Button>
        </div>
      }
    >
      {user && (
        <div className="space-y-5">
          <div className="flex items-center gap-3 p-4 bg-card rounded-xl border border-border">
            <UserAvatar name={user.full_name} email={user.email} />
            <div className="min-w-0">
              <p className="font-semibold text-foreground text-sm">{user.full_name}</p>
              <p className="text-2xs text-muted-foreground truncate">{user.email}</p>
            </div>
          </div>
          {error && <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>}
          <div>
            <label className="text-13 font-medium text-foreground mb-1.5 block">Nombre completo</label>
            <Input {...register("fullName")} placeholder="Nombre completo" />
            {errors.fullName && <p className="text-2xs text-destructive mt-1">{errors.fullName.message}</p>}
          </div>
          {!isSelf && (
            <>
              <div>
                <label className="text-13 font-medium text-foreground mb-1.5 block">Rol</label>
                <Select {...register("role")}>
                  {roles.map((r) => (
                    <SelectOption key={r.name} value={r.name}>{r.display_name}</SelectOption>
                  ))}
                </Select>
              </div>
              <div className="flex items-center gap-3 rounded-lg border px-3 py-2.5 bg-muted/30">
                <Switch checked={watch("isActive")} onCheckedChange={(checked) => setValue("isActive", checked, { shouldDirty: true })} />
                <div>
                  <p className="text-13 font-medium">Estado de acceso</p>
                  <p className="text-2xs text-muted-foreground">{watch("isActive") ? "Activo" : "Inactivo"}</p>
                </div>
              </div>
            </>
          )}
          {isSelf && <p className="text-2xs text-muted-foreground bg-muted/50 px-3 py-2 rounded-lg">Solo puede editar su nombre. No puede cambiar su propio rol.</p>}
          <p className="text-2xs text-muted-foreground">Último acceso: {fmtDate(user.last_login_at)}</p>
        </div>
      )}
    </Modal>
  );
}

const inviteSchema = z.object({
  email: z.string().email("Ingrese un correo válido"),
  role: z.string(),
  days: z.number().int().min(1).max(30),
});

function InvitePanel({ open, availableRoles, onClose, onCreated }: {
  open: boolean; availableRoles: Role[]; onClose: () => void; onCreated: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [generatedUrl, setGeneratedUrl] = useState<string | null>(null);
  const [emailSent, setEmailSent] = useState(true);
  const [copied, setCopied] = useState(false);

  const { register, handleSubmit, control, reset, watch, formState: { errors, isSubmitting } } = useForm<z.infer<typeof inviteSchema>>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: "", role: "viewer", days: 7 },
  });

  useEffect(() => {
    if (!open) { reset({ email: "", role: "viewer", days: 7 }); setError(null); setGeneratedUrl(null); setEmailSent(true); setCopied(false); }
  }, [open, reset]);

  const days = watch("days");

  const onSubmit = handleSubmit(async (data) => {
    setError(null);
    try {
      const { data: result } = await api.post<Invitation>("/users/invitations", {
        email: data.email.trim(), role: data.role, expires_in_days: data.days,
      });
      setGeneratedUrl(buildInviteUrl(result.token));
      setEmailSent(result.email_sent ?? false);
      onCreated();
    } catch (err: unknown) {
      setError(getErrorMessage(err, "No se pudo generar la invitación"));
    }
  });

  const handleCopy = () => {
    if (!generatedUrl) return;
    navigator.clipboard.writeText(generatedUrl).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
  };

  const roles = availableRoles;
  const expiryDate = new Date(Date.now() + days * 864e5).toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Invitar usuario"
      size="lg"
      onSubmit={generatedUrl ? undefined : onSubmit}
      footer={
        generatedUrl ? (
          <Button variant="link" onClick={onClose} className="text-muted-foreground">Cerrar</Button>
        ) : (
          <div className="flex gap-3 w-full">
            <Button variant="outline" className="flex-1 gap-1.5" onClick={onClose} type="button"><X className="w-3.5 h-3.5" /> Cancelar</Button>
            <Button className="flex-1 gap-1.5" type="submit" disabled={isSubmitting}>
              {isSubmitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
              {isSubmitting ? "Enviando..." : "Enviar invitación"}
            </Button>
          </div>
        )
      }
    >
      {generatedUrl ? (
        <div className="flex flex-col items-center justify-center py-8 gap-5 text-center">
          <div className={`w-14 h-14 rounded-2xl flex items-center justify-center ${emailSent ? "bg-success/10" : "bg-warning/10"}`}>
            <CheckCircle className={`w-7 h-7 ${emailSent ? "text-success" : "text-warning"}`} />
          </div>
          <div>
            <p className="font-semibold text-foreground">{emailSent ? "Invitación enviada" : "Invitación creada"}</p>
            <p className="text-sm text-muted-foreground mt-1">
              {emailSent
                ? <>Se envió un correo a <strong>{watch("email")}</strong> con el enlace de acceso.</>
                : <>No se pudo enviar el correo a <strong>{watch("email")}</strong>. Comparte el enlace manualmente.</>}
            </p>
          </div>
          <div className="w-full bg-card border border-border rounded-xl p-4 text-left">
            <p className="text-2xs text-muted-foreground mb-1.5 font-medium uppercase tracking-wide">Enlace de acceso (respaldo)</p>
            <p className="text-xs text-foreground break-all leading-relaxed">{generatedUrl}</p>
          </div>
          <p className="text-2xs text-muted-foreground -mt-2">Si el correo no llega, comparte este enlace manualmente.</p>
          <Button className={`w-full gap-2 ${copied ? "bg-success hover:bg-success" : ""}`} onClick={handleCopy}>
            {copied ? <><Check className="w-4 h-4" /> ¡Copiado!</> : <><Copy className="w-4 h-4" /> Copiar enlace</>}
          </Button>
        </div>
      ) : (
        <div className="space-y-5">
          {error && <Alert variant="destructive"><AlertCircle className="h-4 w-4" /><AlertDescription>{error}</AlertDescription></Alert>}
          <div>
            <label className="text-13 font-medium text-foreground mb-1.5 block">Correo electrónico</label>
            <Input type="email" {...register("email")} placeholder="usuario@empresa.com" />
            {errors.email && <p className="text-2xs text-destructive mt-1">{errors.email.message}</p>}
          </div>
          <div>
            <label className="text-13 font-medium text-foreground mb-1.5 block">Rol asignado</label>
            <Select {...register("role")}>
              {roles.map((r) => (
                <SelectOption key={r.name} value={r.name}>{r.display_name}</SelectOption>
              ))}
            </Select>
          </div>
          <div>
            <label className="text-13 font-medium text-foreground mb-1.5 block">Validez del enlace</label>
            <div className="flex items-center gap-3">
              <Controller
                name="days"
                control={control}
                render={({ field }) => (
                  <Slider value={field.value} onValueChange={field.onChange} min={1} max={30} step={1} className="flex-1" />
                )}
              />
              <span className="text-sm font-semibold text-foreground w-20 text-right">{days} {days === 1 ? "día" : "días"}</span>
            </div>
            <p className="text-2xs text-muted-foreground mt-1">Expira el {expiryDate}</p>
          </div>
        </div>
      )}
    </Modal>
  );
}

function ResetPasswordResultModal({ result, onClose }: {
  result: { user: User; tempPassword: string } | null; onClose: () => void;
}) {
  const { toast } = useToast();

  const handleCopy = () => {
    if (!result) return;
    navigator.clipboard.writeText(result.tempPassword).then(() =>
      toast({ type: "success", message: "Contraseña copiada.", duration: 1500 })
    );
  };

  return (
    <Modal
      open={!!result}
      onClose={onClose}
      title="Contraseña temporal generada"
      size="md"
      footer={
        <Button className="flex-1 gap-1.5" onClick={onClose}>
          <Check className="w-3.5 h-3.5" /> Entendido
        </Button>
      }
    >
      {result && (
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Comparta esta contraseña con <span className="font-semibold text-foreground">{result.user.full_name}</span> por
            un canal seguro. Deberá cambiarla en su próximo inicio de sesión.
          </p>
          <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2.5">
            <code className="flex-1 font-mono text-sm text-foreground tracking-wide select-all">{result.tempPassword}</code>
            <Button variant="ghost" size="icon-xs" onClick={handleCopy} title="Copiar">
              <Copy className="h-3.5 w-3.5" />
            </Button>
          </div>
          <Alert variant="warning">
            <AlertDescription className="text-2xs">
              Esta contraseña no volverá a mostrarse. Si la pierde, deberá generar una nueva.
            </AlertDescription>
          </Alert>
        </div>
      )}
    </Modal>
  );
}

function UsuariosTab() {
  const { user: me } = useAuth();
  const can = usePermission();
  const canManageUsers = can(PERM.USERS_MANAGE);
  const canUpdateUsers = canManageUsers || can(PERM.USERS_UPDATE);
  const canDeleteUsers = canManageUsers || can(PERM.USERS_DELETE);
  const { toast, confirm } = useToast();
  const [editUser, setEditUser] = useState<User | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [resetResult, setResetResult] = useState<{ user: User; tempPassword: string } | null>(null);
  const [usersPage, setUsersPage] = useState(1);
  const [usersPageSize, setUsersPageSize] = useState(20);
  const [invitesPage, setInvitesPage] = useState(1);
  const [invitesPageSize, setInvitesPageSize] = useState(20);

  const { data: usersData, loading, error: usersError, refetch: loadUsers } =
    useApi<{ items: User[]; total: number }>(`/users?page=${usersPage}&page_size=${usersPageSize}`);
  const { data: invitationsData, refetch: loadInvitations } =
    useApi<{ items: Invitation[]; total: number }>(`/users/invitations?active_only=true&page=${invitesPage}&page_size=${invitesPageSize}`);
  const { data: summaryData } = useApi<{ total_members: number; active: number; no_access_yet: number; admins: number }>("/users/summary");
  const { data: rolesData } = useApi<Role[]>("/rbac/roles");
  const users = usersData?.items ?? [];
  const usersTotal = usersData?.total ?? 0;
  const invitations = invitationsData?.items ?? [];
  const invitationsTotal = invitationsData?.total ?? 0;
  const availableRoles = rolesData ?? [];

  useEffect(() => {
    if (usersError) toast({ type: "error", message: "No se pudo cargar la lista de usuarios." });
  }, [usersError, toast]);

  const handleDelete = async (u: User) => {
    const ok = await confirm({ title: `¿Eliminar a ${u.full_name}?`, message: "Esta acción no se puede deshacer", confirmText: "Eliminar", variant: "danger" });
    if (ok) {
      try { await api.delete(`/users/${u.id}`); loadUsers(); toast({ type: "success", message: "Usuario eliminado." }); }
      catch (err: unknown) { toast({ type: "error", message: getErrorMessage(err, "No se pudo eliminar") }); }
    }
  };

  const handleResetPassword = async (u: User) => {
    const ok = await confirm({
      title: `¿Resetear contraseña de ${u.full_name}?`,
      message: "Se generará una contraseña temporal y el usuario deberá cambiarla en su próximo inicio de sesión. Su sesión actual se cerrará.",
      confirmText: "Resetear",
      variant: "danger",
    });
    if (!ok) return;
    try {
      const { data } = await api.post<{ temp_password: string; user: User }>(`/users/${u.id}/reset-password`);
      setResetResult({ user: data.user, tempPassword: data.temp_password });
      loadUsers();
    } catch (err: unknown) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo resetear la contraseña.") });
    }
  };

  const handleCopyInvite = (token: string) => {
    navigator.clipboard.writeText(buildInviteUrl(token)).then(() => toast({ type: "success", message: "Enlace copiado.", duration: 1500 }));
  };

  const handleRevokeInvite = async (inv: Invitation) => {
    const ok = await confirm({ title: "¿Revocar invitación?", message: `El enlace enviado a ${inv.email} dejará de funcionar`, confirmText: "Revocar", variant: "danger" });
    if (ok) {
      try { await api.delete(`/users/invitations/${inv.id}`); loadInvitations(); }
      catch (err) { toast({ type: "error", message: getErrorMessage(err, "No se pudo revocar la invitación.") }); }
    }
  };

  const handleDeleteInvite = async (inv: Invitation) => {
    const ok = await confirm({
      title: "¿Eliminar esta invitación?",
      message: "Se eliminará permanentemente de la lista. Esta acción no se puede deshacer.",
      confirmText: "Eliminar",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.delete(`/users/invitations/${inv.id}/permanent`);
      toast({ type: "success", message: "Invitación eliminada.", duration: 1500 });
      loadInvitations();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo eliminar la invitación.") });
    }
  };

  const handleResendInvite = async (inv: Invitation) => {
    const ok = await confirm({
      title: "¿Reenviar invitación?",
      message: `Se generará un nuevo enlace para ${inv.email} y el anterior dejará de funcionar.`,
      confirmText: "Reenviar",
    });
    if (!ok) return;
    try {
      await api.post(`/users/invitations/${inv.id}/resend`);
      toast({ type: "success", message: "Invitación reenviada." });
      loadInvitations();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo reenviar la invitación.") });
    }
  };

  const pendingInvites = invitations;

  return (
    <div className="space-y-6">
      <EditUserPanel key={editUser?.id} user={editUser} meId={me?.id} availableRoles={availableRoles} onClose={() => setEditUser(null)} onSaved={loadUsers} />
      <InvitePanel key={inviteOpen ? "open" : "closed"} open={inviteOpen} availableRoles={availableRoles} onClose={() => setInviteOpen(false)} onCreated={loadInvitations} />
      <ResetPasswordResultModal result={resetResult} onClose={() => setResetResult(null)} />

      {/* Stats: conteos agregados del equipo completo, independientes de la
          paginación de la tabla - ver GET /users/summary. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard title="Total miembros" value={summaryData?.total_members ?? 0} icon={Users} loading={loading} />
        <StatCard title="Activos" value={summaryData?.active ?? 0} icon={CheckCircle} accent="green" loading={loading} />
        <StatCard title="Sin acceso aún" value={summaryData?.no_access_yet ?? 0} icon={Clock} accent="amber" loading={loading} />
        <StatCard title="Administradores" value={summaryData?.admins ?? 0} icon={ShieldCheck} loading={loading} />
      </div>

      {/* Equipo */}
      <Card className="overflow-hidden">
        <div className="flex flex-col gap-3 px-5 py-4 border-b border-border/60">
          <div className="flex items-center gap-2 min-w-0">
            <h3 className="text-sm font-semibold text-foreground truncate">Equipo</h3>
            <span className="text-2xs px-1.5 py-0.5 rounded-full font-semibold bg-muted text-muted-foreground shrink-0">{usersTotal}</span>
          </div>
          {canManageUsers && (
            <div className="grid grid-cols-1 sm:flex sm:justify-end gap-2">
              <Button size="sm" onClick={() => setInviteOpen(true)} className="gap-1.5">
                <UserPlus className="w-3.5 h-3.5" /> Invitar usuario
              </Button>
            </div>
          )}
        </div>
        <DataTable
          loading={loading}
          skeleton={
            <div className="overflow-x-auto">
              <table className="w-full"><tbody>{[1,2,3,4].map(i => <tr key={i} className="border-b border-border/60"><td className="px-3 py-2"><Skeleton className="h-9 w-full" /></td></tr>)}</tbody></table>
            </div>
          }
          pagination={{ page: usersPage, pageSize: usersPageSize, total: usersTotal, onPageChange: setUsersPage, onPageSizeChange: (n) => { setUsersPageSize(n); setUsersPage(1); }, itemLabel: "miembros" }}
          noCard
          columns={[
            { id: "usuario", header: "Usuario" },
            { id: "rol", header: "Rol", className: "w-36", hideBelow: "sm" },
            { id: "estado", header: "Estado", className: "w-24", hideBelow: "sm" },
            { id: "ultimo_acceso", header: "Último acceso", hideBelow: "lg" },
            { id: "acciones", header: "Acciones", className: "whitespace-nowrap", sticky: true },
          ]}
          data={users}
          rowKey={(u) => u.id}
          renderRow={(u) => (
            <TableRow>
              <TableCell className="max-w-44 sm:max-w-none">
                <div className="flex items-center gap-3 min-w-0">
                  <UserAvatar name={u.full_name} email={u.email} />
                  <div className="min-w-0">
                    <p className="text-13 font-semibold text-foreground truncate leading-tight">{u.full_name}</p>
                    <p className="text-2xs text-muted-foreground truncate">{u.email}</p>
                  </div>
                </div>
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-semibold ${roleBadgeClass(u.role)}`}>
                  {availableRoles.find((r) => r.name === u.role)?.display_name ?? u.role}
                </span>
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${u.is_active ? "text-success" : "text-muted-foreground"}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${u.is_active ? "bg-success" : "bg-muted-foreground"}`} />
                  {u.is_active ? "Activo" : "Inactivo"}
                </span>
              </TableCell>
              <TableCell className="hidden lg:table-cell">
                <span className="text-xs text-muted-foreground tabular-nums">{timeAgo(u.last_login_at)}</span>
              </TableCell>
              <TableCell sticky className="whitespace-nowrap">
                <div className="flex w-full items-center gap-1 justify-end">
                  {(canUpdateUsers || u.id === me?.id) && (
                    <Button variant="ghost" size="icon-xs" onClick={() => setEditUser(u)} title="Editar"><Pencil className="h-3.5 w-3.5" /></Button>
                  )}
                  {canManageUsers && u.id !== me?.id && (
                    <Button variant="ghost" size="icon-xs" onClick={() => handleResetPassword(u)} title="Resetear contraseña"><KeyRound className="h-3.5 w-3.5" /></Button>
                  )}
                  {canDeleteUsers && (
                    <Button variant="ghost" size="icon-xs" onClick={() => handleDelete(u)} disabled={u.id === me?.id} title="Eliminar" className="hover:text-destructive"><Trash2 className="h-3.5 w-3.5" /></Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
          )}
        />
      </Card>

      {/* Invitaciones pendientes */}
      <Card className="overflow-hidden">
        <div className="flex items-center gap-2 px-5 py-4 border-b border-border/60">
          <h3 className="text-sm font-semibold text-foreground">Invitaciones pendientes</h3>
          {invitationsTotal > 0 && (
            <Badge variant="warning" size="xs">{invitationsTotal}</Badge>
          )}
        </div>
        <DataTable
          empty={<EmptyState icon={CheckCircle} title="Sin invitaciones pendientes" description="Todas las invitaciones han sido aceptadas o no hay ninguna activa." className="py-8" />}
          pagination={pendingInvites.length > 0 ? { page: invitesPage, pageSize: invitesPageSize, total: invitationsTotal, onPageChange: setInvitesPage, onPageSizeChange: (n) => { setInvitesPageSize(n); setInvitesPage(1); }, itemLabel: "invitaciones" } : undefined}
          noCard
          columns={[
            { id: "destinatario", header: "Destinatario" },
            { id: "rol", header: "Rol", className: "w-36", hideBelow: "sm" },
            { id: "estado", header: "Estado", className: "w-28", hideBelow: "sm" },
            { id: "expira", header: "Expira", className: "w-32", hideBelow: "sm" },
            { id: "acciones", header: "Acciones", className: "whitespace-nowrap", sticky: true },
          ]}
          data={pendingInvites}
          rowKey={(inv) => inv.id}
          renderRow={(inv) => {
            const status = inviteStatus(inv);
            const statusMeta = INVITE_STATUS_META[status];
            return (
            <TableRow>
              <TableCell className="truncate max-w-40" title={inv.email}>{inv.email}</TableCell>
              <TableCell className="hidden sm:table-cell">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-semibold ${roleBadgeClass(inv.role)}`}>
                  {availableRoles.find((r) => r.name === inv.role)?.display_name ?? inv.role}
                </span>
              </TableCell>
              <TableCell className="hidden sm:table-cell">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-semibold ${statusMeta.className}`}>
                  {statusMeta.label}
                </span>
              </TableCell>
              <TableCell className="hidden sm:table-cell text-xs text-muted-foreground">
                {new Date(inv.expires_at).toLocaleDateString("es-ES", { day: "2-digit", month: "short", year: "numeric" })}
              </TableCell>
              <TableCell sticky className="whitespace-nowrap">
                <div className="flex w-full items-center gap-1 justify-end">
                  {status === "active" && (
                    <Button variant="ghost" size="icon-xs" onClick={() => handleCopyInvite(inv.token)} title="Copiar enlace"><Copy className="w-3.5 h-3.5" /></Button>
                  )}
                  {canManageUsers && status !== "accepted" && (
                    <Button variant="ghost" size="icon-xs" onClick={() => handleResendInvite(inv)} title="Reenviar"><RefreshCw className="w-3.5 h-3.5" /></Button>
                  )}
                  {canManageUsers && status === "active" && (
                    <Button variant="ghost" size="icon-xs" onClick={() => handleRevokeInvite(inv)} className="hover:text-destructive" title="Revocar"><XCircle className="w-3.5 h-3.5" /></Button>
                  )}
                  {canManageUsers && status !== "active" && (
                    <Button variant="ghost" size="icon-xs" onClick={() => handleDeleteInvite(inv)} className="hover:text-destructive" title="Eliminar"><Trash2 className="w-3.5 h-3.5" /></Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
            );
          }}
        />
      </Card>
    </div>
  );
}

export default function UsuariosPage() {
  return <UsuariosTab />;
}
