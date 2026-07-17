/**
 * Permission string constants for the RBAC system.
 * Format: "module.action" — must match MODULES_SEED in backend/services/system/rbac.py.
 *
 * Usage:  const can = usePermission();
 *         if (can(PERM.KNOWLEDGE_UPDATE)) { ... }
 */
export const PERM = {
  DASHBOARD_READ: "dashboard.read",

  CONVERSATIONS_READ:   "conversations.read",
  CONVERSATIONS_UPDATE: "conversations.update",
  CONVERSATIONS_DELETE: "conversations.delete",

  KNOWLEDGE_READ:   "knowledge.read",
  KNOWLEDGE_CREATE: "knowledge.create",
  KNOWLEDGE_UPDATE: "knowledge.update",
  KNOWLEDGE_DELETE: "knowledge.delete",
  KNOWLEDGE_MANAGE: "knowledge.manage",

  ANALYTICS_READ: "analytics.read",

  AUDIT_READ: "audit.read",

  BOT_SETTINGS_READ:   "bot_settings.read",
  BOT_SETTINGS_UPDATE: "bot_settings.update",

  ESCALATION_READ:   "escalation.read",
  ESCALATION_UPDATE: "escalation.update",
  ESCALATION_MANAGE: "escalation.manage",

  USERS_READ:   "users.read",
  USERS_UPDATE: "users.update",
  USERS_DELETE: "users.delete",
  USERS_MANAGE: "users.manage",

  NOTIFICATIONS_READ:   "notifications.read",
  NOTIFICATIONS_UPDATE: "notifications.update",

  SYSTEM_READ:   "system.read",
  SYSTEM_UPDATE: "system.update",
  SYSTEM_MANAGE: "system.manage",
} as const;

export type PermissionKey = typeof PERM[keyof typeof PERM];
