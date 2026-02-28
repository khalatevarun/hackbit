"use client";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useState } from "react";

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
  goals?: {
    name: string;
    agent_template: string;
  } | null;
}

interface AgentMemoryProps {
  states: AgentState[];
}

function actionColor(action: string | undefined): string {
  switch (action) {
    case "escalate": return "bg-red-100 text-red-800";
    case "call":     return "bg-orange-100 text-orange-800";
    case "nudge":    return "bg-yellow-100 text-yellow-800";
    default:         return "bg-green-100 text-green-800";
  }
}

function actionLabel(action: string | undefined): string {
  switch (action) {
    case "escalate": return "urgent";
    case "call":     return "checking in";
    case "nudge":    return "nudging you";
    default:         return "watching";
  }
}

function templateColor(template: string | undefined): string {
  switch (template) {
    case "fitness":     return "bg-green-100 text-green-800";
    case "sleep":       return "bg-indigo-100 text-indigo-800";
    case "money":       return "bg-amber-100 text-amber-800";
    case "social":      return "bg-pink-100 text-pink-800";
    case "short_lived": return "bg-orange-100 text-orange-800";
    default:            return "bg-gray-100 text-gray-800";
  }
}

export function AgentMemory({ states }: AgentMemoryProps) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (states.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Why they said that</CardTitle>
          <CardDescription>
            The context your companions used to reach their conclusions.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-6">
            Share some updates and let your companions check in — their reasoning will appear here.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Why they said that</CardTitle>
        <CardDescription>
          Each companion connects the dots across all your goals before responding.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {states.map((s) => {
          const isOpen = expanded === s.id;
          const template = s.goals?.agent_template;
          const action = s.state.next_action;
          const confidence = s.state.confidence;
          const context = s.state.context_summary?.trim();
          const pattern = s.state.pattern_detected;

          return (
            <div key={s.id} className="border rounded-lg overflow-hidden">
              <button
                className="w-full flex items-center justify-between gap-3 p-3 text-left hover:bg-muted/50 transition-colors"
                onClick={() => setExpanded(isOpen ? null : s.id)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <Badge variant="secondary" className={`shrink-0 text-xs ${templateColor(template)}`}>
                    {s.goals?.name ?? "Goal"}
                  </Badge>
                  {pattern && (
                    <span className="text-xs text-muted-foreground truncate hidden sm:block">
                      {pattern}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {confidence !== undefined && (
                    <span className="text-xs text-muted-foreground">
                      {Math.round(confidence * 100)}% sure
                    </span>
                  )}
                  <Badge variant="outline" className={`text-xs ${actionColor(action)}`}>
                    {actionLabel(action)}
                  </Badge>
                  <span className="text-muted-foreground text-xs">{isOpen ? "▲" : "▼"}</span>
                </div>
              </button>

              {isOpen && (
                <div className="px-3 pb-3 space-y-2 border-t bg-muted/20">
                  <p className="text-xs font-medium text-muted-foreground pt-2 uppercase tracking-wide">
                    Context they had access to
                  </p>
                  {context ? (
                    <p className="text-xs leading-relaxed whitespace-pre-wrap">{context}</p>
                  ) : (
                    <p className="text-xs text-muted-foreground italic">
                      Not enough cross-goal context yet — keep sharing updates.
                    </p>
                  )}
                  <p className="text-xs text-muted-foreground pt-1">
                    Last checked: {new Date(s.updated_at).toLocaleString()}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
