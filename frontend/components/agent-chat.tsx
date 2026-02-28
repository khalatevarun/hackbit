"use client";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

interface ContentSuggestion {
  title: string;
  url: string;
  snippet: string;
  published_date: string;
}

interface AgentMessage {
  id: string;
  from_agent: string;
  to_agent: string | null;
  message: string;
  created_at: string;
  goal_id: string | null;
  context?: {
    content_suggestions?: ContentSuggestion[];
  } | null;
}

interface AgentChatProps {
  messages: AgentMessage[];
}

function companionColor(agent: string): string {
  if (agent.startsWith("fitness"))    return "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200";
  if (agent.startsWith("sleep"))      return "bg-indigo-100 text-indigo-800 dark:bg-indigo-900 dark:text-indigo-200";
  if (agent.startsWith("money"))      return "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200";
  if (agent.startsWith("social"))     return "bg-pink-100 text-pink-800 dark:bg-pink-900 dark:text-pink-200";
  if (agent.startsWith("short_lived") || agent.startsWith("custom")) return "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200";
  if (agent === "coordinator")        return "bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200";
  return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200";
}

const COMPANION_LABELS: Record<string, string> = {
  fitness:     "Fitness",
  sleep:       "Sleep",
  money:       "Money",
  social:      "Social",
  short_lived: "Deadline",
  custom:      "Goal",
  coordinator: "All companions",
};

function companionLabel(agent: string): string {
  const base = agent.split(":")[0];
  return COMPANION_LABELS[base] ?? (base.charAt(0).toUpperCase() + base.slice(1));
}

export function AgentChat({ messages }: AgentChatProps) {
  if (messages.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Your companions</CardTitle>
          <CardDescription>
            Add a goal to get started. Your companions will check in once you share some updates.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground text-center py-8">
            Nothing yet — share what&apos;s going on and your companions will respond.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your companions</CardTitle>
        <CardDescription>
          What they&apos;re saying about your progress.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 max-h-96 overflow-y-auto">
        {messages.map((msg) => (
          <div key={msg.id} className="flex gap-3 items-start">
            <Badge
              variant="secondary"
              className={`shrink-0 text-xs ${companionColor(msg.from_agent)}`}
            >
              {companionLabel(msg.from_agent)}
            </Badge>
            <div className="flex-1 min-w-0">
              <p className="text-sm">{msg.message}</p>
              {msg.context?.content_suggestions && msg.context.content_suggestions.length > 0 && (
                <div className="mt-2 space-y-1">
                  {msg.context.content_suggestions.map((link, i) => (
                    <a
                      key={i}
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block rounded border border-border bg-muted/50 px-2 py-1.5 hover:bg-muted transition-colors"
                    >
                      <p className="text-xs font-medium truncate">{link.title}</p>
                      {link.snippet && (
                        <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">{link.snippet}</p>
                      )}
                    </a>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted-foreground mt-1">
                {new Date(msg.created_at).toLocaleString()}
              </p>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
