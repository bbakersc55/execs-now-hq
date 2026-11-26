/** Names in a list of people (owner, 2026-11-25): a role only where two
 *  people in the same list share a name. */
import { describe, expect, it } from "vitest";
import { apart, roleByCode, roleByName } from "./people";

describe("apart", () => {
  it("names each of two people of one name with their role, by its name", () => {
    const people = [{ name: "Bryan Baker", role: "FF" }, { name: "Jackie Doe", role: "ECC" },
                    { name: "Bryan Baker", role: "FCC" }];
    expect(people.map(apart(people, roleByCode))).toEqual(
      ["Bryan Baker (Practice owner)", "Jackie Doe", "Bryan Baker (Client owner)"]);
  });

  it("takes roles that are names already", () => {
    const people = [{ name: "Bryan Baker", role: "Practice owner" },
                    { name: "Bryan Baker", role: "Client owner" }];
    expect(people.map(apart(people, roleByName)).join(", "))
      .toBe("Bryan Baker (Practice owner), Bryan Baker (Client owner)");
  });

  it("matches names whatever their case and spacing", () => {
    const people = [{ name: "Bryan Baker", role: "FF" }, { name: " bryan  baker", role: "FCC" }];
    const nameOf = apart(people, roleByCode);
    expect(nameOf(people[0])).toBe("Bryan Baker (Practice owner)");
  });

  it("leaves a list with no shared name exactly as it was", () => {
    const people = [{ name: "Jackie Doe", role: "ECC" }, { name: "Michael LeClerc", role: "FCC" }];
    expect(people.map(apart(people, roleByCode))).toEqual(["Jackie Doe", "Michael LeClerc"]);
  });

  it("never shows a role code, and adds nothing when the role isn't known", () => {
    const people = [{ name: "Sam Doe", role: "" }, { name: "Sam Doe", role: null }];
    expect(people.map(apart(people, roleByCode))).toEqual(["Sam Doe", "Sam Doe"]);
    expect(people.map(apart(people, roleByName)).join()).not.toMatch(/\b(FF|FCC|ECC)\b/);
  });
});
