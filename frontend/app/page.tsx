"use client";

import { useCallback, useEffect, useState } from "react";
import { GoalForm } from "@/components/goal-form";
import { ActivityLog } from "@/components/activity-log";
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

export default function Home() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [agentStates, setAgentStates] = useState<AgentState[]>([]);
  const [ticking, setTicking] = useState(false);
  const [tickResult, setTickResult] = useState<string | null>(null);

  const fetchGoals = useCallback(async () => {
    const res = await fetch("/api/goals");
    if (res.ok) setGoals(await res.json());
  }, []);

  const fetchLogs = useCallback(async () => {
    const res = await fetch("/api/logs");
    if (res.ok) setLogs(await res.json());
  }, []);

  const fetchMessages = useCallback(async () => {
    const res = await fetch("/api/agent-messages");
    if (res.ok) setMessages(await res.json());
  }, []);

  const fetchAgentStates = useCallback(async () => {
    const res = await fetch("/api/agent-states");
    if (res.ok) setAgentStates(await res.json());
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

  useEffect(() => {
    fetchGoals();
    fetchLogs();
    fetchMessages();
    fetchAgentStates();
  }, [fetchGoals, fetchLogs, fetchMessages, fetchAgentStates]);

  const activeGoals = goals.filter((g) => g.active);

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">LifeOS</h1>
            <p className="text-sm text-muted-foreground">
              A set of companions that keep you accountable — across every part of your life.
            </p>
          </div>
          <div className="flex items-center gap-3">
            {tickResult && (
              <span className="text-xs text-muted-foreground">{tickResult}</span>
            )}
            <Button onClick={triggerTick} disabled={ticking} size="sm" variant="outline">
              {ticking ? "Checking in…" : "Check in now"}
            </Button>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Left column: add goal + share update */}
          <div className="space-y-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 px-1">
                New goal
              </p>
              <GoalForm onCreated={fetchGoals} />
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 px-1">
                Share an update
              </p>
              <ActivityLog onLogged={fetchLogs} />
            </div>
          </div>

          {/* Middle column: goals + recent updates */}
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
                    Add your first goal above to get started.
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
                        No updates yet — share what&apos;s going on.
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
      </main>
    </div>
  );
}
