import { expect, test } from "@playwright/test";

test("show selected toggles the rendered list", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("4 items")).toBeVisible();
  await page.getByRole("button", { name: "Show selected" }).click();

  await expect(page.getByText("Selected items")).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveText(["Alpha", "Gamma"]);
});
