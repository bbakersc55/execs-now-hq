import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { CLIENT_LANDING, Landing } from "./Landing";

function at(role: string | null) {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <Routes>
        <Route path="/" element={<Landing role={role} staff={<p>Staff dashboard</p>} other={<p>Contacts</p>} />} />
        <Route path={CLIENT_LANDING} element={<p>Our work</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("the landing page", () => {
  it.each(["FCC", "ECC"])("sends a client user (%s) to the portal, never a staff screen", (role) => {
    at(role);
    expect(screen.getByText("Our work")).toBeInTheDocument();
    expect(screen.queryByText("Contacts")).toBeNull();
    expect(screen.queryByText("Staff dashboard")).toBeNull();
  });

  it.each(["FF", "CF", "VA"])("gives the practice's team (%s) the dashboard", (role) => {
    at(role);
    expect(screen.getByText("Staff dashboard")).toBeInTheDocument();
  });
});
