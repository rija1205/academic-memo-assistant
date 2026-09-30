import { NextResponse } from "next/server";

const backendUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${backendUrl}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });

    return NextResponse.json(
      { frontend: "ok", backend: response.ok ? "ok" : "unavailable" },
      { status: response.ok ? 200 : 503 },
    );
  } catch {
    return NextResponse.json(
      { frontend: "ok", backend: "unavailable" },
      { status: 503 },
    );
  }
}
