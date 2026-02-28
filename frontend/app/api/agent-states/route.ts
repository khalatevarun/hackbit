import { NextResponse } from "next/server";
import { supabase, MOCK_USER_ID } from "@/lib/supabase";

export async function GET() {
  const { data, error } = await supabase
    .from("agent_states")
    .select("*, goals(name, agent_template)")
    .eq("user_id", MOCK_USER_ID)
    .order("updated_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
