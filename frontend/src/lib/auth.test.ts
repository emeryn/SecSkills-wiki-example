import { describe, expect, it } from "vitest";
import { safeNextPath } from "./auth";

describe("safeNextPath (open redirect protection)", () => {
  it.each([
    ["/spaces/eng", "/spaces/eng"],
    ["/admin/users?q=bob&page=2", "/admin/users?q=bob&page=2"],
    [null, "/"],
    ["", "/"],
    ["//evil.example", "/"],
    ["/\\evil.example", "/"],
    ["https://evil.example/", "/"],
    ["javascript:alert(1)", "/"],
    ["evil.example", "/"],
    ["/ok\nSet-Cookie: x", "/"],
    ["/path\\with\\backslash", "/"],
    ["/" + "a".repeat(2001), "/"],
  ])("%j -> %j", (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });
});
