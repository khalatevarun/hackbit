"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AgentChat } from "@/components/agent-chat";
import { AgentMemory } from "@/components/agent-memory";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface Goal {
  id: string;
  name: string;
  type: string;
  agent_template: string;
  active: boolean;
  end_at: string | null;
  created_at: string;
}

interface LogEntry {
  id: string;
  content: string;
  created_at: string;
  goals?: { name: string } | null;
}

interface AgentMessage {
  id: string;
  from_agent: string;
  to_agent: string | null;
  message: string;
  created_at: string;
  goal_id: string | null;
}

interface AgentState {
  id: string;
  goal_id: string;
  updated_at: string;
  state: {
    last_checkin?: string;
    pattern_detected?: string | null;
    confidence?: number;
    context_summary?: string;
    next_action?: string;
  };
  goals?: { name: string; agent_template: string } | null;
}

const TEMPLATE_EMOJI: Record<string, string> = {
  fitness:     "🏋️",
  sleep:       "😴",
  money:       "💰",
  social:      "🤝",
  short_lived: "🎯",
  custom:      "✨",
};

const TEMPLATE_COLOR: Record<string, string> = {
  fitness:     "bg-green-100 text-green-800",
  sleep:       "bg-indigo-100 text-indigo-800",
  money:       "bg-amber-100 text-amber-800",
  social:      "bg-pink-100 text-pink-800",
  short_lived: "bg-orange-100 text-orange-800",
  custom:      "bg-gray-100 text-gray-800",
};

const API_TIMEOUT_MS = 12_000;

function fetchWithTimeout(url: string, options?: RequestInit): Promise<Response> {
  const ctrl = new AbortController();
  const id = setTimeout(() => ctrl.abort(), API_TIMEOUT_MS);
  return fetch(url, { ...options, signal: ctrl.signal }).finally(() => clearTimeout(id));
}

export default function DashboardPage() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [loading, setLoading] = useState(true);
  const [ticking, setTicking] = useState(false);
  const [tickResult, setTickResult] = useState<string | null>(null);
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoResult, setDemoResult] = useState<string | null>(null);

  const fetchGoals = useCallback(async () => {
    try {
      const res = await fetchWithTimeout("/api/goals");
      if (res.ok) setGoals(await res.json());
    } catch {
      setGoals([]);
    }
  }, []);

  const fetchLogs = useCallback(async () => {
    try {
      const res = await fetchWithTimeout("/api/logs");
      if (res.ok) setLogs(await res.json());
    } catch {
      setLogs([]);
    }
  }, []);

  const fetchMessages = useCallback(async () => {
    try {
      const res = await fetchWithTimeout("/api/agent-messages");
      if (res.ok) setMessages(await res.json());
    } catch {
      setMessages([]);
    }
  }, []);

  const fetchAgentStates = useCallback(async () => {
    try {
      const res = await fetchWithTimeout("/api/agent-states");
      if (res.ok) setAgentStates(await res.json());
    } catch {
      setAgentStates([]);
    }
  }, []);

  const triggerTick = useCallback(async () => {
    setTicking(true);
    setTickResult(null);
    try {
      const res = await fetch("/api/trigger-tick", { method: "POST" });
      const data = await res.json();
      if (data.status === "ok") {
        setTickResult(`${data.goals_processed} companion${data.goals_processed !== 1 ? "s" : ""} checked in`);
      } else if (data.status === "skipped") {
        setTickResult("Nothing to check in on yet");
      } else {
        setTickResult(data.error || "Something went wrong");
      }
      fetchGoals();
      fetchLogs();
      fetchMessages();
      fetchAgentStates();
    } catch {
      setTickResult("Couldn't reach your companions");
    } finally {
      setTicking(false);
    }
  }, [fetchGoals, fetchLogs, fetchMessages, fetchAgentStates]);

  const triggerDemo = useCallback(async (action: "nightly_summary" | "proactive_nudges" | "checkin") => {
    setDemoLoading(true);
    setDemoResult(null);
    try {
      const res = await fetch("/api/trigger-demo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = await res.json();
      if (data.status === "ok") {
        if (data.users_processed != null) {
          const msg = data.message ?? `Sent to ${data.users_processed}/${data.users_total ?? data.users_processed} users`;
          const extra =
            action === "proactive_nudges" && (data.nudge_count > 0 || data.logcheck_count > 0)
              ? ` (${data.nudge_count ?? 0} nudges, ${data.logcheck_count ?? 0} log-checks)`
              : "";
          setDemoResult(msg + extra);
        } else if (action === "nightly_summary") setDemoResult("Nightly summary sent to Telegram");
        else if (action === "checkin") setDemoResult("Check-in sent to Telegram");
        else
          setDemoResult(
            `${data.nudge_count ?? 0} nudge(s), ${data.logcheck_count ?? 0} log-check(s) sent to Telegram`
          );
      } else if (data.status === "skipped") {
        setDemoResult(data.message ?? "Skipped");
      } else {
        setDemoResult(data.message ?? "Something went wrong");
      }
    } catch {
      setDemoResult("Could not reach demo endpoint");
    } finally {
      setDemoLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.allSettled([
      fetchGoals(),
      fetchLogs(),
      fetchMessages(),
      fetchAgentStates(),
    ]).finally(() => setLoading(false));
  }, [fetchGoals, fetchLogs, fetchMessages, fetchAgentStates]);

  const activeGoals = goals.filter((g) => g.active);

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center">
        <div className="text-center space-y-3">
          <p className="text-muted-foreground">Loading dashboard…</p>
          <p className="text-xs text-muted-foreground">Fetching goals, logs, and companion messages</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center gap-4 min-w-0">
            <Link href="/" className="text-sm text-muted-foreground hover:text-foreground shrink-0">
              Home
            </Link>
            <div className="min-w-0">
              <h1 className="text-xl font-bold tracking-tight truncate">HACKBITZ</h1>
              <p className="text-xs text-muted-foreground truncate">
                Companions that keep you accountable across your life.
              </p>
            </div>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Left column: goals + recent updates */}
          <div className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">
                  What you&apos;re working on
                  {activeGoals.length > 0 && (
                    <span className="ml-2 text-sm font-normal text-muted-foreground">
                      {activeGoals.length} active
                    </span>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {activeGoals.length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    Add goals via Telegram to get started.
                  </p>
                )}
                {activeGoals.map((goal) => (
                  <div
                    key={goal.id}
                    className="flex items-center justify-between p-3 rounded-lg border"
                  >
                    <div className="min-w-0">
                      <p className="font-medium text-sm truncate">{goal.name}</p>
                      {goal.end_at && (
                        <p className="text-xs text-muted-foreground">
                          Due {new Date(goal.end_at).toLocaleDateString()}
                        </p>
                      )}
                    </div>
                    <span className="ml-2 shrink-0 text-lg" title={goal.agent_template}>
                      {TEMPLATE_EMOJI[goal.agent_template] ?? "✨"}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Tabs defaultValue="updates">
              <TabsList className="w-full">
                <TabsTrigger value="updates" className="flex-1">Recent updates</TabsTrigger>
                <TabsTrigger value="all" className="flex-1">All goals</TabsTrigger>
              </TabsList>

              <TabsContent value="updates">
                <Card>
                  <CardContent className="pt-4 space-y-3 max-h-80 overflow-y-auto">
                    {logs.length === 0 && (
                      <p className="text-sm text-muted-foreground text-center py-4">
                        No updates yet — send a message in Telegram to log.
                      </p>
                    )}
                    {logs.map((log) => (
                      <div key={log.id} className="text-sm border-b pb-2 last:border-0">
                        <p className="leading-snug">{log.content}</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {new Date(log.created_at).toLocaleString()}
                          {log.goals?.name && (
                            <span className="ml-2 text-xs opacity-70">
                              · {log.goals.name}
                            </span>
                          )}
                        </p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="all">
                <Card>
                  <CardContent className="pt-4 space-y-2">
                    {goals.length === 0 && (
                      <p className="text-sm text-muted-foreground text-center py-4">No goals yet.</p>
                    )}
                    {goals.map((goal) => (
                      <div
                        key={goal.id}
                        className="flex items-center justify-between text-sm border-b pb-2 last:border-0"
                      >
                        <span className={goal.active ? "" : "line-through text-muted-foreground"}>
                          {goal.name}
                        </span>
                        <Badge
                          variant="secondary"
                          className={`text-xs ${TEMPLATE_COLOR[goal.agent_template] ?? TEMPLATE_COLOR.custom}`}
                        >
                          {goal.active ? "active" : "done"}
                        </Badge>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          </div>

          {/* Right column: companion messages + reasoning */}
          <div className="space-y-6">
            <AgentChat messages={messages} />
            <AgentMemory states={agentStates} />
          </div>
        </div>

        {/* Actions section at the bottom */}
        <section className="mt-12 pt-8 border-t">
          <h2 className="text-sm font-medium text-muted-foreground mb-3">Actions</h2>
          <div className="flex flex-wrap gap-2">
            <Button onClick={triggerTick} disabled={ticking} size="sm" variant="default">
              {ticking ? "Checking in…" : "Check in now"}
            </Button>
            <Button
              onClick={() => triggerDemo("nightly_summary")}
              disabled={demoLoading}
              size="sm"
              variant="outline"
            >
              Send nightly summary
            </Button>
            <Button
              onClick={() => triggerDemo("proactive_nudges")}
              disabled={demoLoading}
              size="sm"
              variant="outline"
            >
              Send proactive nudges
            </Button>
            <Button
              onClick={() => triggerDemo("checkin")}
              disabled={demoLoading}
              size="sm"
              variant="outline"
            >
              Send check-in to Telegram
            </Button>
          </div>
          {(tickResult || demoResult) && (
            <p className="text-xs text-muted-foreground mt-2">{tickResult ?? demoResult}</p>
          )}
        </section>
      </main>
    </div>
  );
}
