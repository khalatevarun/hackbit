import { NextRequest, NextResponse } from "next/server";
import { supabase, MOCK_USER_ID } from "@/lib/supabase";
import { groqComplete, parseGroqJSON } from "@/lib/groq";

const CLASSIFY_LOG_PROMPT = `You match a user's journal/log entry to the most relevant active goal.

Return ONLY valid JSON, no other text:
{ "goal_id": "best matching goal id or null", "confidence": 0.0-1.0, "reason": "one short phrase" }

Rules:
- Always pick the single best match if one exists, even if uncertain.
- confidence >= 0.7 means you're sure it fits.
- confidence < 0.7 means it's a guess — the user will be asked to confirm.
- If truly nothing fits at all, return goal_id: null with confidence: 0.
- A log about skipping the gym → fitness goal
- A log about sleep → sleep goal
- A log about spending money → money goal
- A log about friends/family → social goal
- Progress on a project → short_lived goal
- General feelings/stress with no clear domain → null`;

interface LogClassification {
  goal_id: string | null;
  confidence: number;
  reason?: string;
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

  let classifiedGoalId: string | null = null;
  let confidence = 0;
  let suggestion: {
    goal_id: string;
    goal_name: string;
    agent_template: string;
    reason: string;
    confidence: number;
  } | null = null;

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
      confidence = result.confidence ?? 0;

      if (result.goal_id && goals.some((g) => g.id === result.goal_id)) {
        classifiedGoalId = result.goal_id;

        if (confidence < 0.7) {
          const matchedGoal = goals.find((g) => g.id === result.goal_id);
          suggestion = {
            goal_id: result.goal_id,
            goal_name: matchedGoal?.name ?? "Unknown",
            agent_template: matchedGoal?.agent_template ?? "custom",
            reason: result.reason ?? "",
            confidence,
          };
        }
      }
    }
  } catch {
    // Silently fall through — log will be saved without a goal link
  }

  // Low confidence → save without goal, return suggestion for UI confirmation
  const row: Record<string, unknown> = {
    user_id: MOCK_USER_ID,
    content,
    source: "manual_input",
  };
  if (classifiedGoalId && confidence >= 0.7) {
    row.goal_id = classifiedGoalId;
  }

  const { data, error } = await supabase.from("user_logs").insert(row).select().single();
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // If confident, fire reactive tick immediately
  if (confidence >= 0.7) {
    const triggerUrl = process.env.MODAL_TRIGGER_URL_FOR_USER;
    if (triggerUrl) {
      fetch(triggerUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: MOCK_USER_ID }),
      }).catch(() => {});
    }
  }

  return NextResponse.json(
    { ...data, suggestion: suggestion ?? null },
    { status: 201 },
  );
}

export async function PATCH(req: NextRequest) {
  const body = await req.json();
  const logId: string | undefined = body.log_id;
  const goalId: string | undefined = body.goal_id;

  if (!logId) {
    return NextResponse.json({ error: "log_id is required" }, { status: 400 });
  }

  const updateFields: Record<string, unknown> = {};
  if (goalId) {
    updateFields.goal_id = goalId;
  }

  const { data, error } = await supabase
    .from("user_logs")
    .update(updateFields)
    .eq("id", logId)
    .eq("user_id", MOCK_USER_ID)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  // Fire reactive tick now that the log has a goal
  if (goalId) {
    const triggerUrl = process.env.MODAL_TRIGGER_URL_FOR_USER;
    if (triggerUrl) {
      fetch(triggerUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: MOCK_USER_ID }),
      }).catch(() => {});
    }
  }

  return NextResponse.json(data);
}
