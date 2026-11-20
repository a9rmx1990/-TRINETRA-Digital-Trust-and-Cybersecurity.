/**
 * Browser walkthrough against a fresh backend serving the built frontend.
 * Run scripts/e2e.sh, which starts an isolated backend with an empty database.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { compose, onboard, record } from "./helpers";

const PASSWORD = process.env.E2E_ANALYST_PASSWORD ?? "e2e-analyst-password";

async function analystLogin(page: Page) {
  await page.goto("/analyst");
  await page.getByLabel("Workspace password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Case investigations" })).toBeVisible();
}

test.describe("fresh start and ownership", () => {
  test("empty workspace, records survive reload, another session cannot see them", async ({ page, browser }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Request money with a spoken confirmation" })).toBeVisible();
    await onboard(page, "HDFC00011111");
    await page.reload();
    await expect(page.getByLabel("Request from")).toContainText("Meera Iyer");
    const other = await browser.newContext();
    const p2 = await other.newPage();
    await p2.goto("/");
    await expect(p2.getByRole("heading", { name: "Open a sandbox account" })).toBeVisible();
    await other.close();
    const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(axe.violations.map((v) => v.id)).toEqual([]);
  });
});

test.describe("customer to analyst and back", () => {
  test("Gemini analyst verifies an incoming request and the customer sees it settle automatically", async ({ page, browser }) => {
    await onboard(page, "HDFC00044444");
    await compose(page, "25000");
    await expect(page.getByLabel("Request summary")).toContainText("₹25,000.00");
    await record(page);
    await expect(page.getByText("Recording accepted")).toBeVisible({ timeout: 20_000 });
    await page.getByRole("button", { name: "Review request" }).click();
    await page.getByRole("button", { name: "Request ₹25,000.00" }).click();
    await expect(page.getByRole("heading", { name: "Waiting for verification" })).toBeVisible();
    await expect(page.getByText("This receipt updates automatically after analyst verification.")).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Verification code" })).toHaveCount(0);

    const analystContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const analyst = await analystContext.newPage();
    await analystLogin(analyst);
    await analyst.getByRole("button", { name: /₹25,000\.00/ }).click();
    await expect(analyst.getByText("Incoming money request", { exact: true })).toBeVisible();
    await expect(analyst.getByText("inconclusive suspicion", { exact: true })).toBeVisible();
    const verify = analyst.getByRole("button", { name: "Verify it" });
    await expect(verify).toBeDisabled();
    await analyst.getByRole("button", { name: "Run analysis" }).click();
    await expect(verify).toBeEnabled();
    await verify.click();
    await expect(analyst.getByText("Verified · Incoming transfer settled")).toBeVisible();
    const axe = await new AxeBuilder({ page: analyst }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(axe.violations.flatMap((v) => v.nodes.map((n) => `${v.id} ${n.target.join(" ")} ${(n.any[0]?.message ?? "").slice(0, 90)}`))).toEqual([]);

    await expect(page.getByRole("heading", { name: "Request verified" })).toBeVisible();
    await expect(page.getByRole("status").getByText("₹25,000.00 received in your sandbox account.")).toBeVisible();
    await page.getByRole("button", { name: "Dismiss verification confirmation" }).click();
    await expect(page.getByRole("button", { name: "Dismiss verification confirmation" })).toHaveCount(0);
    await page.getByRole("button", { name: "View request history" }).click();
    await expect(page.getByRole("listitem").filter({ hasText: "₹25,000.00" })).toContainText("Approved");

    await analyst.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(analyst.getByRole("region", { name: "Selected case" }).getByText("SETTLED", { exact: true })).toBeVisible();
    await analystContext.close();
  });
});

test.describe("narrow screen", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("old SOC links open the Gemini analyst sign-in", async ({ page }) => {
    await page.goto("/soc/case/old-link");
    await expect(page).toHaveURL(/\/analyst$/);
    await expect(page.getByRole("heading", { name: "Analyst sign-in" })).toBeVisible();
  });
});
