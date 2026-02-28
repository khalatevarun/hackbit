"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";

interface ActivityLogProps {
  onLogged: () => void;
}

export function ActivityLog({ onLogged }: ActivityLogProps) {
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;

    setLoading(true);
    try {
      await fetch("/api/logs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: content.trim() }),
      });
      setContent("");
      onLogged();
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
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
      </CardContent>
    </Card>
  );
}
