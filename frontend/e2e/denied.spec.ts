import { expect, test } from "@playwright/test";
import { compose, onboard } from "./helpers";

test.describe("microphone denied", () => {
  test("denial keeps the draft and blocks submission", async ({ browser }) => {
    const ctx = await browser.newContext({ permissions: [] });
    const page = await ctx.newPage();
    await onboard(page, "HDFC00022222");
    await compose(page, "1250");
    await page.getByLabel("I agree to voice screening for this request.").check();
    await page.getByRole("button", { name: "Start microphone" }).click();
    await expect(page.getByText("Microphone access is blocked")).toBeVisible();
    await expect(page.getByRole("button", { name: "Review request" })).toBeDisabled();
    await page.getByRole("button", { name: "Edit details" }).click();
    await expect(page.getByLabel("Amount")).toHaveValue("1,250");
    await ctx.close();
  });
});

