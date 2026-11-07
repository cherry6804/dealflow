import { describe, expect, it } from "vitest";

import type { Property } from "../../services/propertyApi";
import { EMPTY_PROPERTY_FORM, formatAmount, propertyPriceLabel, propertyStatusTone, validatePropertyForm } from "./property-workflow";

const BASE: Property = {
  id: "p1",
  organization_id: "org-1",
  created_at: "2026-01-05T10:00:00Z",
  updated_at: "2026-01-06T10:00:00Z",
  status: "AVAILABLE",
  transaction_type: "SALE",
  price: "7500000",
  currency: "INR",
  rent: null,
  security_deposit: null,
  maintenance_charge: null,
  address_line_1: "12 Lake Road",
  address_line_2: null,
  locality: "Lakeside",
  city: "Pune",
  state: "MH",
  postal_code: null,
  property_type: "APARTMENT",
  bhk: 3,
  built_up_area: null,
  carpet_area: null,
  floor_number: null,
  total_floors: null,
};

describe("property validation", () => {
  it("requires the address, location and the price for a sale", () => {
    const errors = validatePropertyForm(EMPTY_PROPERTY_FORM);
    expect(errors.address_line_1).toBe("Enter the first address line.");
    expect(errors.locality).toBe("Enter the locality.");
    expect(errors.price).toBe("Enter the sale price.");
    expect(errors.rent).toBeUndefined();
  });

  it("requires a rent for rent and lease, and rejects a floor above the total", () => {
    const errors = validatePropertyForm({
      ...EMPTY_PROPERTY_FORM,
      address_line_1: "A",
      locality: "B",
      city: "C",
      state: "D",
      transaction_type: "RENT",
      floor_number: "9",
      total_floors: "3",
    });
    expect(errors.rent).toBe("Enter the monthly rent.");
    expect(errors.price).toBeUndefined();
    expect(errors.floor_number).toBe("Floor number cannot be greater than total floors.");
  });
});

describe("property display", () => {
  it("shows the sale price, or the monthly rent for a rental", () => {
    expect(propertyPriceLabel(BASE)).toContain("75,00,000");
    expect(propertyPriceLabel({ ...BASE, transaction_type: "RENT", rent: "25000" })).toMatch(/\/month$/);
  });

  it("formats missing amounts as a dash", () => {
    expect(formatAmount(null)).toBe("—");
    expect(formatAmount("not a number")).toBe("—");
  });

  it("maps availability to a status tone", () => {
    expect(propertyStatusTone("AVAILABLE")).toBe("success");
    expect(propertyStatusTone("RESERVED")).toBe("pending");
    expect(propertyStatusTone("SOLD")).toBe("active");
    expect(propertyStatusTone("UNAVAILABLE")).toBe("danger");
    expect(propertyStatusTone(null)).toBe("neutral");
  });
});
