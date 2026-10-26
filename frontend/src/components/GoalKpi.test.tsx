import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GoalKpiCard, GoalKpiLine } from "./GoalKpi";
import { aMe, aWorkParent } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

const KPI = { kpi: "k1", name: "On-time delivery", value: 82, value_text: "82%",
  target_text: "target 95%", status: "behind", status_label: "Behind",
  period: "the week of October 19", whose: "", off_track_run: 0 };

describe("a goal's KPI (M5 ties)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("the card shows the latest reading, target, status and period", () => {
    renderRoute(<GoalKpiLine kpi={KPI} />);
    const line = screen.getByLabelText("KPI: On-time delivery");
    expect(line).toHaveTextContent("82%");
    expect(line).toHaveTextContent("target 95%");
    expect(line).toHaveTextContent("Behind");
    expect(line).toHaveTextContent("the week of October 19");
  });

  it("says whose number a per-person KPI is, and draws nothing with no KPI", () => {
    const view = renderRoute(<GoalKpiLine kpi={{ ...KPI, name: "Calls", whose: "yours", value_text: "12" }} />);
    expect(screen.getByLabelText("KPI: Calls (yours)")).toHaveTextContent("12");
    view.unmount();
    const { container } = renderRoute(<GoalKpiLine kpi={null} />);
    expect(container.querySelector(".goal-kpi")).toBeNull();
  });

  it("the practice owner links one of the company's KPIs to the goal", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PATCH /api/goals/g1/": aWorkParent({ id: "g1", kind: "goal", kpi: KPI }),
      "GET /api/scorecard/setup/": { exists: true, pages: [], kpis: [
        { id: "k1", name: "On-time delivery", archived: false },
        { id: "k2", name: "Retired", archived: true }] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<GoalKpiCard me={aMe({ role: "FF" })}
      goal={aWorkParent({ id: "g1", kind: "goal", client_company: "c1", kpi: null })} />);
    const picker = await screen.findByLabelText("KPI it shows");
    await waitFor(() => expect(screen.getByRole("option", { name: "On-time delivery" })).toBeInTheDocument());
    expect(screen.queryByRole("option", { name: "Retired" })).toBeNull();
    await user.selectOptions(picker, "k1");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual({ kpi: "k1" }));
  });

  it("a client sees the linked KPI and no picker; with none, no card", () => {
    const view = renderRoute(<GoalKpiCard me={aMe({ role: "ECC" })}
      goal={aWorkParent({ id: "g1", kind: "goal", client_company: "c1", kpi: KPI })} />);
    expect(screen.getByLabelText("KPI: On-time delivery")).toBeInTheDocument();
    expect(screen.queryByLabelText("KPI it shows")).toBeNull();
    view.unmount();
    const { container } = renderRoute(<GoalKpiCard me={aMe({ role: "ECC" })}
      goal={aWorkParent({ id: "g1", kind: "goal", client_company: "c1", kpi: null })} />);
    expect(container.textContent).toBe("");
  });
});
