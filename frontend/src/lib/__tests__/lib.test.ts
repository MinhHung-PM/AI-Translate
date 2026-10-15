import { describe, expect, it } from "vitest";
import { fromForm, toForm, type FieldDef } from "@/components/memo/item-fields";
import { ApiError, buildQuery } from "@/lib/api";
import { errorMessage, formatMs, formatUsd, zonedLocalToIso } from "@/lib/format";
import { parseParticipants } from "@/lib/participants";

describe("buildQuery", () => {
  it("skips empty values and repeats arrays", () => {
    expect(buildQuery({ a: "x", b: "", c: undefined, d: null, s: ["open", "done"], n: 0 })).toBe("?a=x&s=open&s=done&n=0");
    expect(buildQuery({})).toBe("");
  });
});

describe("format", () => {
  it("formats transcript timestamps", () => {
    expect(formatMs(62_000)).toBe("01:02");
    expect(formatMs(3_723_000)).toBe("01:02:03");
    expect(formatMs(null)).toBe("");
  });
  it("labels costs in USD", () => {
    expect(formatUsd("0.0012")).toBe("$0.0012");
    expect(formatUsd(12.5)).toBe("$12.50");
  });
  it("converts a wall-clock time in a timezone to UTC", () => {
    expect(zonedLocalToIso("2026-10-14T10:00", "Asia/Tokyo")).toBe("2026-10-14T01:00:00.000Z");
    expect(zonedLocalToIso("2026-10-14T10:00", "Asia/Ho_Chi_Minh")).toBe("2026-10-14T03:00:00.000Z");
  });
  it("maps API error codes to Vietnamese messages", () => {
    expect(errorMessage(new ApiError(429, "rate_limited", "Too many"))).toContain("quá nhiều");
    expect(errorMessage(new ApiError(422, "validation_failed", "Bad file"))).toBe("Bad file");
    expect(errorMessage(new Error("x"))).toContain("lỗi");
  });
});

describe("participants", () => {
  it("parses name | organization lines", () => {
    expect(parseParticipants("田中 | Sakura\n\n Nguyen An ")).toEqual([
      { display_name: "田中", organization: "Sakura" },
      { display_name: "Nguyen An", organization: null },
    ]);
  });
});

describe("item form mapping", () => {
  const fields: FieldDef[] = [
    { name: "description", label: "d", type: "textarea" },
    { name: "owner_text", label: "o", type: "text" },
    { name: "due_needs_confirmation", label: "c", type: "checkbox" },
  ];
  it("round-trips and converts blanks to null", () => {
    const form = toForm({ description: "x", owner_text: null, due_needs_confirmation: true } as never, fields);
    expect(form).toEqual({ description: "x", owner_text: "", due_needs_confirmation: true });
    expect(fromForm({ ...form, owner_text: "  " }, fields)).toEqual({ description: "x", owner_text: null, due_needs_confirmation: true });
  });
});
