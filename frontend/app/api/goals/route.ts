import { NextRequest, NextResponse } from "next/server";
import { supabase, MOCK_USER_ID } from "@/lib/supabase";
import { groqComplete, parseGroqJSON } from "@/lib/groq";

const CLASSIFY_GOAL_PROMPT = `You classify a user's natural-language goal description into a structured goal.

Categories:
- fitness: workouts, gym, running, exercise, sports, steps, activity
- sleep: sleep, rest, bedtime, wake up, sleep quality, tiredness
- money: budget, spending, saving, finances, expenses, costs, debt
- social: friends, family, social life, relationships, calls, meetups, loneliness
- short_lived: one-time goals with a clear deadline (projects, events, exams, trips)
- custom: anything that doesn't fit the above

Return ONLY valid JSON, no other text:
{
  "agent_template": "fitness|sleep|money|social|short_lived|custom",
  "goal_type": "habit|short_lived",
  "name": "concise goal name, max 40 chars, written as a goal not a sentence",
  "config": {
    // fitness:     { "frequency_per_week": number, "target": "activity description" }
    // sleep:       { "target_hours": number, "target_bedtime": "HH:MM" }
    // money:       { "weekly_budget": number, "watch_categories": string[] }
    // social:      { "min_social_per_week": number }
    // short_lived: { "end_date": "YYYY-MM-DD", "success_criteria": "what done looks like" }
    // custom:      {}
  }
}`;

interface ClassifiedGoal {
  agent_template: string;
  goal_type: string;
  name: string;
  config: Record<string, unknown>;
}

export async function GET() {
  const { data, error } = await supabase
    .from("goals")
    .select("*")
    .eq("user_id", MOCK_USER_ID)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const description: string = body.description?.trim() ?? "";

  if (!description) {
    return NextResponse.json({ error: "description is required" }, { status: 400 });
  }

  // Classify the natural-language description into a structured goal
  let classified: ClassifiedGoal = {
    agent_template: "custom",
    goal_type: "habit",
    name: description.slice(0, 40),
    config: {},
  };

  try {
    const raw = await groqComplete(
      CLASSIFY_GOAL_PROMPT,
      `User said: "${description}"${body.end_at ? `\nDeadline: ${body.end_at}` : ""}`,
    );
    classified = parseGroqJSON<ClassifiedGoal>(raw);
  } catch {
    // Fall through with defaults — never block goal creation
  }

  const row: Record<string, unknown> = {
    user_id: MOCK_USER_ID,
    name: classified.name,
    type: classified.goal_type,
    agent_template: classified.agent_template,
    config: classified.config,
    active: true,
  };

  // Deadline: prefer explicit end_at from client, fall back to config.end_date
  const endAt = body.end_at ?? classified.config?.end_date;
  if (endAt) {
    row.end_at = new Date(endAt as string).toISOString();
    // Short-lived goals need end_date in config too
    if (!classified.config.end_date) {
      row.config = { ...classified.config, end_date: endAt };
    }
  }

  const { data, error } = await supabase.from("goals").insert(row).select().single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
