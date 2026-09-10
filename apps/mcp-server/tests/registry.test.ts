import { describe, expect, it } from "vitest";

import { isMutating, TOOL_META } from "../src/registry.js";

describe("MCP tool registry", () => {
  it("exposes the twelve contract tools", () => {
    expect(TOOL_META.map((t) => t.name)).toEqual([
      "get_project", "get_revision", "compare_revisions", "get_component",
      "get_component_properties", "get_dependencies", "search_requirements",
      "get_requirement", "get_revision_history", "get_findings",
      "create_review_finding", "update_finding_status",
    ]);
  });

  it("marks exactly the two writers as mutating", () => {
    expect(TOOL_META.filter((t) => t.mutating).map((t) => t.name).sort()).toEqual([
      "create_review_finding", "update_finding_status",
    ]);
    expect(isMutating("get_dependencies")).toBe(false);
    expect(isMutating("create_review_finding")).toBe(true);
  });

  it("gives every tool a description and permission", () => {
    for (const t of TOOL_META) {
      expect(t.description.length).toBeGreaterThan(10);
      expect(t.permission).toMatch(/^[a-z]+:[a-z_]+$/);
    }
  });
});
