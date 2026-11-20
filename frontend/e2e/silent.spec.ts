import { expect, test } from "@playwright/test";
import { compose, onboard, record } from "./helpers";

test.describe("silent capture", () => {
  test("silence is rejected with guidance", async ({ page }) => {
    await onboard(page, "HDFC00033333");
    await compose(page, "500");
    await record(page, 2500);
    await expect(page.getByText("Record again", { exact: true })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Review request" })).toBeDisabled();
  });
});

