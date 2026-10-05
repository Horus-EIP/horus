import { describe, it, expect } from "vitest";
import { namesAlreadyStored } from "@/lib/knowledge-store/stored-names";

describe("namesAlreadyStored", () => {
  it("returns the names that match a stored title, ignoring case and spaces", () => {
    expect(
      namesAlreadyStored(
        [" 4_expense_policy.MD", "Board_Minutes.md"],
        ["4_Expense_Policy.md", "5_IT_Security_Policy.md"]
      )
    ).toEqual([" 4_expense_policy.MD"]);
  });

  it("returns nothing when the store is empty", () => {
    expect(namesAlreadyStored(["a.md"], [])).toEqual([]);
  });

  it("skips entries without a name", () => {
    expect(namesAlreadyStored(["", "a.md"], ["", "a.md"])).toEqual(["a.md"]);
  });
});
