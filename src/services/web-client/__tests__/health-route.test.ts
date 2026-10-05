import { describe, it, expect } from "vitest";
import { GET } from "@/app/api/health/route";

describe("GET /api/health", () => {
  it("answers 200 with the web client's health payload", async () => {
    const response = GET();

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      status: "healthy",
      service: "web-client",
    });
  });
});
