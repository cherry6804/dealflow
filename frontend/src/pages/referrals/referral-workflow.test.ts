import { describe, expect, it } from "vitest";

import { EMPTY_REFERRAL_FORM, referralToPayload, referralStatusLabel, referralStatusTone, validateReferralForm } from "./referral-workflow";

describe("referral validation", () => {
  it("requires a name and a link to a customer, referrer or deal", () => {
    const errors = validateReferralForm(EMPTY_REFERRAL_FORM);
    expect(errors.referral_name).toBe("Enter the referral name.");
    expect(errors.customer_profile_id).toBe("Link the referral to a customer, referring contact, or deal.");
  });

  it("accepts a referral linked to a referring contact", () => {
    const errors = validateReferralForm({ ...EMPTY_REFERRAL_FORM, referral_name: "Asha", referrer_contact_id: "c1" });
    expect(errors).toEqual({});
  });

  it("rejects an invalid email", () => {
    const errors = validateReferralForm({ ...EMPTY_REFERRAL_FORM, referral_name: "Asha", deal_id: "d1", referral_email: "asha@" });
    expect(errors.referral_email).toBe("Enter a valid email address.");
  });
});

describe("referral payload and labels", () => {
  it("sends blank optional fields as null and trims the name", () => {
    const payload = referralToPayload({ ...EMPTY_REFERRAL_FORM, referral_name: "  Asha  ", referrer_contact_id: "c1" });
    expect(payload.referral_name).toBe("Asha");
    expect(payload.referral_phone).toBeNull();
    expect(payload.customer_profile_id).toBeNull();
    expect(payload.referrer_contact_id).toBe("c1");
  });

  it("labels and tones each status", () => {
    expect(referralStatusLabel("NOT_CONVERTED")).toBe("Not converted");
    expect(referralStatusTone("CONVERTED")).toBe("success");
    expect(referralStatusTone("NOT_CONVERTED")).toBe("danger");
  });
});
