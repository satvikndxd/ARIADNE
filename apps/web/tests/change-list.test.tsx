import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChangeList } from "../src/components/ChangeList";
import type { ChangeOut } from "../src/types/api";

const change = (over: Partial<ChangeOut> = {}): ChangeOut => ({
  id: "ch_1",
  change_type: "DIMENSION_CHANGE",
  component_id: "cmp_motor_mount",
  component_name: "Motor Mount",
  title: "flange diameter: Ø48.0 ±0.10 → Ø52.0 ±0.05",
  old_value: "48.0",
  new_value: "52.0",
  unit: "mm",
  numeric_delta: 4,
  location: { x: 10, y: 10, width: 100, height: 20 },
  confidence: 0.94,
  severity: "high",
  classification: "consequential",
  detection_method: "hybrid",
  description: "",
  drawing_id: "dwg_b",
  revision_a: "Rev A",
  revision_b: "Rev B",
  metadata: {},
  ...over,
});

describe("ChangeList", () => {
  it("lists changes and reports selection", () => {
    const onSelect = vi.fn();
    render(<ChangeList changes={[change(), change({ id: "ch_2", title: "M6 tapped hole added", severity: "medium" })]} selected={null} onSelect={onSelect} />);
    expect(screen.getByText(/flange diameter/)).toBeInTheDocument();
    expect(screen.getByText(/M6 tapped hole added/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/M6 tapped hole added/));
    expect(onSelect).toHaveBeenCalledWith("ch_2");
  });

  it("shows an empty state", () => {
    render(<ChangeList changes={[]} selected={null} onSelect={() => undefined} />);
    expect(screen.getByText("no changes detected")).toBeInTheDocument();
  });
});
