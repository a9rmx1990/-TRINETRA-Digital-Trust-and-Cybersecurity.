import { expect, type Page } from "@playwright/test";

export async function onboard(page: Page, ref: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Open a sandbox account" })).toBeVisible();
  await expect(page.getByText("Banking sandbox")).toBeVisible();
  await page.getByLabel("Account name").fill("Household");
  await page.getByRole("button", { name: "Create sandbox account" }).click();
  await expect(page.getByRole("heading", { name: "Who are you requesting money from?" })).toBeVisible();
  await page.getByLabel("Name").fill("Meera Iyer");
  await page.getByLabel("Sandbox account reference").fill(ref);
  await page.getByRole("button", { name: "Add contact" }).click();
  await expect(page.getByRole("heading", { name: "Request money" })).toBeVisible();
}

export async function compose(page: Page, amount: string) {
  await page.getByLabel("Request from").selectOption({ index: 1 });
  await page.getByLabel("Amount").fill(amount);
  await page.getByRole("button", { name: "Continue to voice confirmation" }).click();
  await expect(page.getByRole("heading", { name: "Confirm by voice" })).toBeVisible();
}

export async function record(page: Page, seconds = 3500) {
  await page.getByLabel("I agree to voice screening for this request.").check();
  await page.getByRole("button", { name: "Start microphone" }).click();
  await expect(page.getByText("Recording", { exact: true })).toBeVisible();
  await page.waitForTimeout(seconds);
  await page.getByRole("button", { name: "Stop" }).click();
}

