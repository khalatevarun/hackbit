"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";

interface Suggestion {
  goal_id: string;
  goal_name: string;
  agent_template: string;
  reason: string;
  confidence: number;
}

interface PendingLog {
  id: string;
  suggestion: Suggestion;
}

const TEMPLATE_EMOJI: Record<string, string> = {
  sleep: "🌙",
  fitness: "🏃",
  money: "💰",
  social: "🤝",
  short_lived: "📚",
  custom: "📚",
};

interface ActivityLogProps {
  onLogged: () => void;
}

export function ActivityLog({ onLogged }: ActivityLogProps) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);
  const [pending, setPending] = useState<PendingLog | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;

    setLoading(true);
    try {
      const res = await fetch("/api/logs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: content.trim() }),
      });
      const data = await res.json();

      if (data.suggestion) {
        setPending({ id: data.id, suggestion: data.suggestion });
        setContent("");
      } else {
        setContent("");
        setPending(null);
        onLogged();
      }
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm() {
    if (!pending) return;
    setConfirming(true);
    try {
      await fetch("/api/logs", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          log_id: pending.id,
          goal_id: pending.suggestion.goal_id,
        }),
      });
      setPending(null);
      onLogged();
    } finally {
      setConfirming(false);
    }
  }

  function handleDismiss() {
    setPending(null);
    onLogged();
  }

  const emoji = pending
    ? TEMPLATE_EMOJI[pending.suggestion.agent_template] ?? "📌"
    : "";

  return (
    <Card>
      <CardContent className="pt-6">
        {pending ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              This sounds like it could be part of{" "}
              <span className="font-medium text-foreground">
                {emoji} {pending.suggestion.goal_name}
              </span>
              . Should I log it there?
            </p>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={handleConfirm}
                disabled={confirming}
                className="flex-1"
              >
                {confirming
                  ? "Saving…"
                  : `Yes, log under ${pending.suggestion.goal_name}`}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleDismiss}
                disabled={confirming}
              >
                Just save it
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <Textarea
              placeholder="What's going on? e.g. Skipped the gym today, slept only 5 hours, ordered takeout again…"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={3}
              required
              className="text-sm resize-none"
            />
            <Button
              type="submit"
              disabled={loading || !content.trim()}
              className="w-full"
            >
              {loading ? "Sharing…" : "Share update"}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
