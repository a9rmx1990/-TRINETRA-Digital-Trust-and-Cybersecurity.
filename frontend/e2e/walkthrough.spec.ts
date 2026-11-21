/**
 * Browser walkthrough against a fresh backend serving the built frontend.
 * Run scripts/e2e.sh, which starts an isolated backend with an empty database.
 */
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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
  test("a clip selected before consent is screened after consent", async ({ page }) => {
    await onboard(page, "HDFC00055555");
    await compose(page, "24000");

    const chooser = page.waitForEvent("filechooser");
    await page.getByLabel("Choose audio file", { exact: true }).click();
    await (await chooser).setFiles(resolve("e2e", "speech-like.wav"));
    await expect(page.getByText("Check the voice screening box above to analyze this file.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Review request" })).toBeDisabled();

    await page.getByLabel("I agree to voice screening for this request.").check();
    await expect(page.getByRole("button", { name: "Review request" })).toBeEnabled({ timeout: 20_000 });
    await page.getByRole("button", { name: "Review request" }).click();
    await page.getByRole("button", { name: "Request ₹24,000.00" }).click();
    await expect(page.getByRole("heading", { name: "Waiting for verification" })).toBeVisible();
  });

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
    await expect(analyst.getByText("Limited evidence", { exact: true })).toBeVisible();
    const screening = analyst.getByRole("list", { name: "Screening signals" });
    await expect(screening.getByRole("listitem")).toHaveCount(4);
    await screening.getByRole("link", { name: "Voice authenticity" }).click();
    await expect(analyst).toHaveURL(/#aw-evidence-E\d+$/);
    const verify = analyst.getByRole("button", { name: "Verify it" });
    await expect(verify).toBeDisabled();
    await analyst.getByRole("button", { name: "Run analysis" }).click();
    await expect(verify).toBeEnabled();
    const stages = analyst.getByRole("list", { name: "Analysis stages" });
    await expect(stages.getByRole("button")).toHaveCount(5);
    await stages.getByRole("button", { name: /Investigator/ }).click();
    await expect(analyst.getByRole("heading", { name: "Investigator" })).toBeVisible();
    const visuals = analyst.getByRole("region", { name: "Investigator visualizations" });
    await expect(analyst.getByRole("region", { name: "Transaction risk assessment" })).toContainText("Insufficient settled history");
    await expect(visuals.getByRole("heading", { name: "Recipient network" })).toBeVisible();
    await expect(visuals.getByRole("heading", { name: "Voice timeline" })).toBeVisible();
    await expect(visuals.getByText("Voiced", { exact: true })).toBeVisible();
    await visuals.getByRole("button", { name: "Show table" }).click();
    await expect(visuals.getByRole("table")).toContainText("Proposed");
    await visuals.getByRole("button", { name: "Show chart" }).click();
    await stages.getByRole("button", { name: /Monitor/ }).click();
    const watch = analyst.getByRole("region", { name: "Watch status" });
    await expect(watch.getByText("Active", { exact: true })).toBeVisible();
    await expect(watch.getByText("Next check", { exact: true })).toBeVisible();
    await expect(watch.getByText("No checks completed yet.")).toBeVisible();
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
    const intelligence = analyst.getByRole("navigation", { name: "Transaction Intelligence" });
    await intelligence.getByRole("link", { name: "Transaction Risk Monitor" }).click();
    const riskTable = analyst.getByRole("table", { name: "Transaction risk results" });
    const settled = riskTable.getByRole("row").filter({ hasText: "settled" }).filter({ hasText: "25,000" });
    await settled.getByRole("button").click();
    await expect(analyst.getByRole("meter", { name: "Transaction risk score" })).toBeVisible();
    await intelligence.getByRole("link", { name: "AML Monitoring" }).click();
    await expect(analyst.getByText("No matching AML alerts.")).toBeVisible();
    await intelligence.getByRole("link", { name: "Risk Configuration" }).click();
    await expect(analyst.getByRole("heading", { name: "Sandbox rules · sandbox-1" })).toBeVisible();
    await analystContext.close();
  });
});

test("settled transfers produce an AML alert that an analyst can review", async ({ page, request }) => {
  const session = await request.post("/api/v2/analyst/login", { data: { username: "admin", password: PASSWORD } });
  expect(session.ok()).toBeTruthy();
  const analystHeaders = { Authorization: "Bearer " + (await session.json()).token };
  const ref = "AML" + crypto.randomUUID().replaceAll("-", "").slice(0, 12);
  const senders: { headers: Record<string, string>; account: string; beneficiary: string }[] = [];
  for (let i = 0; i < 3; i++) {
    const customer = await request.post("/api/v2/session");
    const headers = { Authorization: "Bearer " + (await customer.json()).token };
    const account = await request.post("/api/v2/accounts", { headers, data: { display_name: "AML sender" } });
    const beneficiary = await request.post("/api/v2/beneficiaries", {
      headers, data: { display_name: "Common recipient", account_ref: ref },
    });
    expect(account.ok() && beneficiary.ok()).toBeTruthy();
    senders.push({ headers, account: (await account.json()).id, beneficiary: (await beneficiary.json()).id });
  }
  // The repository fixture is a 44-byte PCM WAV header followed by 16 kHz mono audio.
  const pcm = readFileSync(resolve("e2e", "speech-like.wav")).subarray(44, 44 + 96_000);
  for (const { headers, account, beneficiary } of [...senders, senders[0]]) {
    const started = await request.post("/api/v2/calls", { headers, data: { consent: true } });
    const call = "/api/v2/calls/" + (await started.json()).id;
    for (let offset = 0; offset < pcm.length; offset += 32_000) {
      expect((await request.post(call + "/pcm", { headers, data: pcm.subarray(offset, offset + 32_000) })).ok()).toBeTruthy();
    }
    expect((await request.post(call + "/finish", { headers })).ok()).toBeTruthy();
    const submit = await request.post("/api/v2/payments", { headers: { ...headers, "Idempotency-Key": crypto.randomUUID() },
      data: { account_id: account, beneficiary_id: beneficiary, amount_minor: 100_000, channel: "IMPS",
        call_id: call.split("/").at(-1) } });
    expect(submit.status()).toBe(201);
    const receipt = await submit.json();
    if (receipt.state === "VERIFICATION_REQUIRED") {
      await expect(async () => {
        const queue = await request.get("/api/v2/analyst/cases", { headers: analystHeaders });
        const item = (await queue.json()).items.find((row: { payment_id: string }) => row.payment_id === receipt.payment_id);
        expect(item).toBeDefined();
        const challenge = await request.post(`/api/v2/analyst/cases/${item.case_id}/verification-code`, {
          headers: analystHeaders, data: { expected_version: item.version, rationale: "Verified test sender" },
        });
        expect(challenge.ok()).toBeTruthy();
      }).toPass({ timeout: 6_000 });
      const payment = "/api/v2/payments/" + receipt.payment_id;
      const details = await request.get(payment, { headers });
      const code = (await details.json()).challenge.delivery_code;
      const verified = await request.post(payment + "/verify", { headers, data: { code } });
      expect((await verified.json()).outcome).toBe("verified");
    } else expect(receipt.state).toBe("SETTLED");
  }

  await analystLogin(page);
  await page.getByRole("link", { name: "AML Monitoring" }).click();
  const alert = page.getByRole("table", { name: "AML alerts" }).getByRole("row").filter({ hasText: "common beneficiary pattern" });
  await alert.getByRole("button").click();
  const details = page.getByRole("region", { name: "AML alert details" });
  await expect(details.getByText("Distinct senders")).toBeVisible();
  await details.getByText("Supporting transfers").click();
  await expect(details.getByRole("table").getByRole("row")).toHaveCount(5);
  await details.getByLabel("Set investigation status").selectOption("UNDER_REVIEW");
  await details.getByLabel("Review note").fill("Review the four settled transfers.");
  await details.getByRole("button", { name: "Save AML review" }).click();
  await expect(page.getByText("Review saved.")).toBeVisible();
  await expect(details.getByText("under review", { exact: true })).toBeVisible();
});

test.describe("narrow screen", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("old SOC links open the Gemini analyst sign-in", async ({ page }) => {
    await page.goto("/soc/case/old-link");
    await expect(page).toHaveURL(/\/analyst$/);
    await expect(page.getByRole("heading", { name: "Analyst sign-in" })).toBeVisible();
  });
});
