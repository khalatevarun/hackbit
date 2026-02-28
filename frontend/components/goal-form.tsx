"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";

interface GoalFormProps {
  onCreated: () => void;
}

export function GoalForm({ onCreated }: GoalFormProps) {
  const [description, setDescription] = useState("");
  const [deadline, setDeadline] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!description.trim()) return;

    setLoading(true);
    try {
      await fetch("/api/goals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          description: description.trim(),
          end_at: deadline || undefined,
        }),
      });
      setDescription("");
      setDeadline("");
      onCreated();
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card>
      <CardContent className="pt-6">
        <form onSubmit={handleSubmit} className="space-y-3">
          <Input
            placeholder="What do you want to work on? e.g. Sleep 8 hours a night, Go to the gym 3x a week, Save $500 by March…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            required
            className="text-sm"
          />
          <div className="flex gap-2">
            <div className="flex-1">
              <Label htmlFor="deadline" className="text-xs text-muted-foreground mb-1 block">
                Deadline <span className="font-normal">(optional)</span>
              </Label>
              <Input
                id="deadline"
                type="date"
                value={deadline}
                onChange={(e) => setDeadline(e.target.value)}
                className="text-sm"
              />
            </div>
            <div className="flex items-end">
              <Button type="submit" disabled={loading || !description.trim()}>
                {loading ? "Adding…" : "Add goal"}
              </Button>
            </div>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
