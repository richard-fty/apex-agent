import { expect, test } from "@playwright/test";

test("empty state appears when the item source is empty", async ({ page }) => {
  await page.route("**/src/items.js", async (route) => {
    await route.fulfill({
      contentType: "text/javascript",
      body: "export const items = [];",
    });
  });

  await page.goto("/");

  await expect(page.getByText("No items match your filters.")).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveCount(0);
});
