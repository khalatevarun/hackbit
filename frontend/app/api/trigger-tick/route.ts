import { NextResponse } from "next/server";

export async function POST() {
  const url = process.env.MODAL_TRIGGER_URL;
  if (!url) {
    return NextResponse.json(
      {
        error:
          "MODAL_TRIGGER_URL not set. Deploy the Modal app (`modal deploy backend/modal_app/app.py`) " +
          "and add the trigger_tick URL to your .env.local as MODAL_TRIGGER_URL.",
      },
      { status: 503 },
    );
  }

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });

    const data = await res.json();
    return NextResponse.json(data, { status: res.status });
  } catch (err) {
    return NextResponse.json(
      { error: `Could not reach Modal endpoint: ${err}` },
      { status: 502 },
    );
  }
}
