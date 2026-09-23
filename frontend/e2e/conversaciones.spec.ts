import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test.describe("Conversaciones", () => {
  test("assistant messages render markdown, not raw syntax", async ({ page }) => {
    await page.goto("/dashboard/conversaciones");
    const firstItem = page.locator('button[aria-pressed]').first();
    const hasConversations = await firstItem
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasConversations) {
      test.skip(true, "no conversations in this environment to assert against");
    }
    await firstItem.click();

    const assistantBubble = page.locator(".md-content").first();
    await expect(assistantBubble).toBeVisible({ timeout: 10_000 });

    const bubbleText = await assistantBubble.innerText();
    expect(bubbleText).not.toMatch(/\*\*[^*]+\*\*/);
    expect(bubbleText).not.toMatch(/^#{1,6}\s/m);
  });

  test("delete conversation action is a visible labeled button", async ({ page }) => {
    await page.goto("/dashboard/conversaciones");
    const firstItem = page.locator('button[aria-pressed]').first();
    const hasConversations = await firstItem
      .waitFor({ state: "visible", timeout: 15_000 })
      .then(() => true)
      .catch(() => false);
    if (!hasConversations) {
      test.skip(true, "no conversations in this environment to assert against");
    }
    await firstItem.click();

    const deleteButton = page.getByRole("button", { name: /eliminar/i });
    await expect(deleteButton).toBeVisible();
  });
});
