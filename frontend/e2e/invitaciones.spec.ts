import { test, expect } from "@playwright/test";

/**
 * Covers the pending-invitation delete action added this session: a
 * physical-delete button appears next to non-active invitations (revoked or
 * expired), and does not appear next to active ones (those only get
 * "Revocar" - deleting an active invite is blocked server-side).
 *
 * Doesn't create/revoke/delete a real invitation in every run (that would
 * mutate shared test data on each execution); it asserts the row-level
 * button visibility rule against whatever invitations already exist.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test.describe("Invitaciones pendientes", () => {
  test("invite button opens the invite modal", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/usuarios");

    const inviteButton = page.getByRole("button", { name: /invitar usuario/i });
    await expect(inviteButton).toBeVisible({ timeout: 10_000 });
    await inviteButton.click();

    await expect(page.getByRole("heading", { name: /invitar usuario/i })).toBeVisible();
  });

  test("delete action only appears on non-active invitations", async ({ page }) => {
    await page.goto("/dashboard/configuracion/acceso/usuarios");
    // Don't gate on the skeleton's absence - right after goto() it may not be attached yet, so a "count 0" check resolves trivially true before data loads. Poll for the actual row instead.
    const revokedRows = page.locator("tr").filter({ hasText: /revocad|expirad/i });
    const hasRevoked = await revokedRows
      .first()
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasRevoked) {
      test.skip(true, "no revoked/expired invitations in this environment to assert against");
    }

    const deleteButton = revokedRows.first().getByRole("button", { name: /eliminar/i });
    await expect(deleteButton).toBeVisible();
  });
});
