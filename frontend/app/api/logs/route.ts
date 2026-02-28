import { NextRequest, NextResponse } from "next/server";
import { supabase, MOCK_USER_ID } from "@/lib/supabase";
import { groqComplete, parseGroqJSON } from "@/lib/groq";

const CLASSIFY_LOG_PROMPT = `You match a user's journal/log entry to the most relevant active goal.

Return ONLY valid JSON, no other text:
{ "goal_id": "the matching goal id, or null if none clearly fits" }

Rules:
- Pick the single best match. If genuinely ambiguous, return null.
- A log about skipping the gym → fitness goal
- A log about sleep → sleep goal
- A log about spending money → money goal
- A log about friends/family → social goal
- Progress on a project → short_lived goal
- General feelings/stress with no clear domain → null`;

interface LogClassification {
  goal_id: string | null;
}

export async function GET() {
  const { data, error } = await supabase
    .from("user_logs")
    .select("*, goals(name)")
    .eq("user_id", MOCK_USER_ID)
    .order("created_at", { ascending: false })
    .limit(50);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const content: string = body.content?.trim() ?? "";

  if (!content) {
    return NextResponse.json({ error: "content is required" }, { status: 400 });
  }

  // Fetch active goals so the LLM can pick from them
  let classifiedGoalId: string | null = null;
  try {
    const { data: goals } = await supabase
      .from("goals")
      .select("id, name, agent_template, type")
      .eq("user_id", MOCK_USER_ID)
      .eq("active", true);

    if (goals && goals.length > 0) {
      const goalList = goals
        .map((g) => `- id: ${g.id} | name: "${g.name}" | type: ${g.agent_template}`)
        .join("\n");

      const raw = await groqComplete(
        CLASSIFY_LOG_PROMPT,
        `Active goals:\n${goalList}\n\nUser log: "${content}"`,
      );
      const result = parseGroqJSON<LogClassification>(raw);
      // Validate the returned ID is actually one of the active goals
      if (result.goal_id && goals.some((g) => g.id === result.goal_id)) {
        classifiedGoalId = result.goal_id;
      }
    }
  } catch {
    // Silently fall through — log will be saved without a goal link
  }

  const row: Record<string, unknown> = {
    user_id: MOCK_USER_ID,
    content,
    source: "manual_input",
  };
  if (classifiedGoalId) {
    row.goal_id = classifiedGoalId;
  }

  const { data, error } = await supabase.from("user_logs").insert(row).select().single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
