import { NextResponse } from "next/server";
import packageJson from "@/package.json";

export function GET() {
  return NextResponse.json({
    status: "healthy",
    service: "web-client",
    version: packageJson.version,
  });
}
