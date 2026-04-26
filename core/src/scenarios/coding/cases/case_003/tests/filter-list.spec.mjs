import { expect, test } from "@playwright/test";

test("search input filters the visible items", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("textbox", { name: "Search items" }).fill("alp");

  await expect(page.getByText("Alpha")).toBeVisible();
  await expect(page.getByText("Beta")).toHaveCount(0);
  await expect(page.getByText("1 items")).toBeVisible();
});
