import { NextResponse } from "next/server";

const VALID_ACTIONS = ["nightly_summary", "proactive_nudges", "checkin"] as const;
type DemoAction = (typeof VALID_ACTIONS)[number];

export async function POST(request: Request) {
  const url = process.env.MODAL_TRIGGER_DEMO_URL;
  if (!url) {
    return NextResponse.json(
      {
        status: "error",
        message:
          "MODAL_TRIGGER_DEMO_URL not set. Deploy the Modal app and add the trigger_demo_action URL to .env.local.",
      },
      { status: 503 },
    );
  }

  let body: { action?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { status: "error", message: "Invalid JSON body" },
      { status: 400 },
    );
  }

  const action = body?.action;
  if (!action || !VALID_ACTIONS.includes(action as DemoAction)) {
    return NextResponse.json(
      {
        status: "error",
        message: `action must be one of: ${VALID_ACTIONS.join(", ")}`,
      },
      { status: 400 },
    );
  }

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, send_to_all: true }),
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.ok ? 200 : 502 });
  } catch (err) {
    return NextResponse.json(
      { status: "error", message: `Could not reach Modal endpoint: ${err}` },
      { status: 502 },
    );
  }
}
