import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../../lib/api";
import type { Lead } from "../../../services/leadApi";
import type { Property } from "../../../services/propertyApi";
import { siteVisitsApi } from "../../../services/siteVisitApi";
import { ScheduleVisitDialog } from "./SiteVisitForms";

vi.mock("../../../services/siteVisitApi", () => ({
  siteVisitsApi: { list: vi.fn(), schedule: vi.fn(), recordAttendance: vi.fn() },
}));
vi.mock("../../../services/followUpApi", () => ({
  followUpsApi: { list: vi.fn(async () => []), createFromSiteVisit: vi.fn() },
}));

const OWNER_CONFLICT = "The owner already has a site visit at this time. Choose another time.";

const property = {
  id: "property-1",
  address_line_1: "Sea View 2BHK",
  locality: "Whitefield",
} as unknown as Property;

const lead = { id: "lead-1", status: "QUALIFIED" } as unknown as Lead;

function renderDialog(onSaved = vi.fn()) {
  render(
    <ScheduleVisitDialog
      properties={[property]}
      leads={[lead]}
      customers={[]}
      leadLabel={() => "Asha Rao"}
      onClose={vi.fn()}
      onSaved={onSaved}
    />,
  );
  return onSaved;
}

function chooseTargetsAndSubmit() {
  fireEvent.change(screen.getByRole("combobox", { name: /^property/i }), { target: { value: property.id } });
  fireEvent.change(screen.getByRole("combobox", { name: /^lead/i }), { target: { value: lead.id } });
  const form = document.getElementById("schedule-visit-form");
  if (!(form instanceof HTMLFormElement)) throw new Error("schedule form not found");
  fireEvent.submit(form);
}

describe("ScheduleVisitDialog owner conflict", () => {
  beforeEach(() => {
    vi.mocked(siteVisitsApi.schedule).mockReset();
  });

  it("shows the server's owner-conflict message and keeps the form open", async () => {
    vi.mocked(siteVisitsApi.schedule).mockRejectedValue(new ApiError(OWNER_CONFLICT, 409));
    const onSaved = renderDialog();

    chooseTargetsAndSubmit();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(OWNER_CONFLICT);
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByRole("combobox", { name: /^property/i })).toBeTruthy();
  });

  it("reports a saved visit once the server accepts it", async () => {
    vi.mocked(siteVisitsApi.schedule).mockResolvedValue({} as never);
    const onSaved = renderDialog();

    chooseTargetsAndSubmit();

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("Site visit scheduled successfully."));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
