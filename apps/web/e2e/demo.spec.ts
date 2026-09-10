/**
 * Critical end-to-end scenario (spec §36):
 * open project → select revisions → run analysis → see changes → click component
 * → dependencies → evidence → ask question → agent uses retrieval → request
 * finding → confirmation modal → confirm → finding appears.
 *
 * Requires: api (:8000) seeded, web dev/preview (:5173), optionally mcp (:8765).
 */
import { expect, test } from "@playwright/test";

test("revision review demo flow", async ({ page }) => {
  await page.goto("/revisions");
  await expect(page.getByText("ORION EV / REVISIONS")).toBeVisible();

  // run analysis
  await page.getByRole("button", { name: "Analyze Revision" }).click();
  await expect(page.getByText(/changes · \d+/)).toBeVisible({ timeout: 60_000 });

  // click the flange change
  await page.getByText(/flange diameter/).first().click();
  await expect(page.getByText("deterministic checks")).toBeVisible();
  await expect(page.getByText(/ORN-FS-017 §4.2/)).toBeVisible();

  // dependencies page
  await page.getByRole("link", { name: "Dependencies" }).click();
  await expect(page.getByText(/store: (sql|neo4j)/)).toBeVisible();
  await expect(page.getByText("Chassis Interface").first()).toBeVisible();

  // evidence via standards search
  await page.getByRole("link", { name: "Standards" }).click();
  await page.getByPlaceholder(/search standards/).fill("radial clearance M10 fastener");
  await page.getByRole("button", { name: "search" }).click();
  await expect(page.getByText(/ORN-FS-017/).first()).toBeVisible({ timeout: 30_000 });

  // chat: question → retrieval → propose finding → confirm
  await page.getByRole("link", { name: "Chat" }).click();
  await page.getByPlaceholder(/ask about changes/).fill("Why is Motor Mount classified as high impact?");
  await page.getByRole("button", { name: "send" }).click();
  await expect(page.getByText(/ORN-FS-017 §4.2/).first()).toBeVisible({ timeout: 60_000 });

  await page.getByPlaceholder(/ask about changes/).fill("Create a review finding for the possible clearance conflict.");
  await page.getByRole("button", { name: "send" }).click();
  await expect(page.getByText("human confirmation required")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: /Confirm · create_review_finding/ }).click();
  await expect(page.getByText(/finding created/)).toBeVisible({ timeout: 30_000 });

  // finding appears in Findings
  await page.getByRole("link", { name: "Findings" }).click();
  await expect(page.getByText(/potential impact on Motor Mount/i).first()).toBeVisible({ timeout: 30_000 });

  // audit trail shows the tool execution
  await page.getByRole("link", { name: "Audit" }).click();
  await expect(page.getByText("create_review_finding").first()).toBeVisible();
});
