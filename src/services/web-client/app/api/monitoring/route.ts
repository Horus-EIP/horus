import { NextRequest, NextResponse } from "next/server";
import { requireAdmin } from "@/lib/server/require-admin";
import { monitoringState } from "@/lib/server/monitoring";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest): Promise<Response> {
  const guard = await requireAdmin(request);
  if (!guard.ok) return guard.response;
  return NextResponse.json({ monitoring: monitoringState() });
}
