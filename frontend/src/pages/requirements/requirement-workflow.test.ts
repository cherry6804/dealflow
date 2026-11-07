import { describe, expect, it } from "vitest";

import { bhkError, budgetError, budgetRange, parkingSpacesError, requirementCustomerName } from "./requirement-workflow";

describe("requirement validation", () => {
  it("accepts an empty or ordered budget and rejects bad ones", () => {
    expect(budgetError("", "")).toBeNull();
    expect(budgetError("5000000", "7000000")).toBeNull();
    expect(budgetError("abc", "")).toBe("Enter valid budget amounts.");
    expect(budgetError("-1", "")).toBe("Budget cannot be negative.");
    expect(budgetError("8000000", "7000000")).toBe("Minimum budget cannot exceed maximum budget.");
  });

  it("requires positive whole BHK values in order", () => {
    expect(bhkError("2", "3")).toBeNull();
    expect(bhkError("1.5", "")).toBe("BHK values must be positive whole numbers.");
    expect(bhkError("4", "2")).toBe("Minimum BHK cannot exceed maximum BHK.");
  });

  it("requires a positive whole number of parking spaces when one is given", () => {
    expect(parkingSpacesError("")).toBeNull();
    expect(parkingSpacesError("2")).toBeNull();
    expect(parkingSpacesError("0")).toBe("Minimum parking spaces must be a positive whole number.");
  });
});

describe("requirement display", () => {
  it("shows a single-ended or unset budget plainly", () => {
    expect(budgetRange({ budget_min: null, budget_max: null })).toBe("Not set");
    expect(budgetRange({ budget_min: null, budget_max: "7000000" })).toMatch(/^Up to ₹/);
    expect(budgetRange({ budget_min: "5000000", budget_max: null })).toMatch(/^From ₹/);
  });

  it("names an unassigned requirement plainly", () => {
    expect(requirementCustomerName({ customer_name: null })).toBe("Customer not assigned");
    expect(requirementCustomerName({ customer_name: "Asha Rao" })).toBe("Asha Rao");
  });
});
