import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceBadge, SeverityBadge, StatusBadge } from "../src/components/badges";

describe("badges", () => {
  it("renders severity text", () => {
    render(<SeverityBadge severity="high" />);
    expect(screen.getByText("high")).toBeInTheDocument();
  });

  it("renders confidence as percent", () => {
    render(<ConfidenceBadge value={0.89} />);
    expect(screen.getByText("89%")).toBeInTheDocument();
  });

  it("normalises status labels", () => {
    render(<StatusBadge status="needs_review" />);
    expect(screen.getByText("needs review")).toBeInTheDocument();
  });
});
