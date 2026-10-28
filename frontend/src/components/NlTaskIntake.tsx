import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  api,
  type ConfirmDraft,
  type ExtractResponse,
  type TaskDraft,
  type TaskPriority,
} from "@/lib/api";

function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function toIso(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function draftToEditable(d: TaskDraft): ConfirmDraft {
  return {
    title: d.title,
    description: d.description,
    priority: d.priority,
    due_at: d.due_at,
    explicit_remind_at: d.explicit_remind_at,
  };
}

export function NlTaskIntake() {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ExtractResponse | null>(null);
  const [edits, setEdits] = useState<ConfirmDraft[]>([]);

  const extract = useMutation({
    mutationFn: () =>
      api.extractTasks({
        text,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      }),
    onSuccess: (data) => {
      setError(null);
      setExtraction(data);
      setEdits(data.drafts.map(draftToEditable));
    },
    onError: (err: Error) => setError(err.message),
  });

  const confirm = useMutation({
    mutationFn: () => {
      if (!extraction) throw new Error("No proposal");
      return api.confirmNlProposal(extraction.proposal_id, { drafts: edits });
    },
    onSuccess: () => {
      setError(null);
      setExtraction(null);
      setEdits([]);
      setText("");
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const reject = useMutation({
    mutationFn: () => {
      if (!extraction) throw new Error("No proposal");
      return api.rejectNlProposal(extraction.proposal_id);
    },
    onSuccess: () => {
      setExtraction(null);
      setEdits([]);
      setError(null);
    },
    onError: (err: Error) => setError(err.message),
  });

  function updateEdit(index: number, patch: Partial<ConfirmDraft>) {
    setEdits((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  return (
    <section className="space-y-4 rounded-xl border border-border/80 bg-white/80 p-5">
      <div>
        <h2 className="font-display text-xl font-semibold">Natural language</h2>
        <p className="text-sm text-muted-foreground">
          Paste what you need to do. Review the draft, then confirm — nothing is saved until you
          approve.
        </p>
      </div>

      {!extraction ? (
        <div className="space-y-3">
          <Label htmlFor="nl-text">Describe your task</Label>
          <Textarea
            id="nl-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="e.g. Finish the Q3 report tomorrow, high priority, remind me in 2 hours"
            rows={4}
          />
          <Button
            type="button"
            disabled={!text.trim() || extract.isPending}
            onClick={() => extract.mutate()}
          >
            {extract.isPending ? "Extracting…" : "Extract draft"}
          </Button>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-muted-foreground">
            Proposal <span className="font-mono">{extraction.proposal_id.slice(0, 8)}</span> ·
            provider {extraction.llm_provider}
            {extraction.notes ? ` · ${extraction.notes}` : ""}
          </p>

          {extraction.needs_clarification && extraction.clarification_questions.length > 0 && (
            <div className="rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-sm">
              <p className="font-medium">Needs clarification</p>
              <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                {extraction.clarification_questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
              <p className="mt-1 text-muted-foreground">Edit the draft below, then confirm.</p>
            </div>
          )}

          {edits.map((draft, index) => (
            <div
              key={index}
              className="grid gap-3 rounded-lg border border-border/60 bg-secondary/40 p-4 md:grid-cols-2"
            >
              <div className="space-y-2 md:col-span-2">
                <Label>Title</Label>
                <Input
                  value={draft.title}
                  onChange={(e) => updateEdit(index, { title: e.target.value })}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>Description</Label>
                <Textarea
                  value={draft.description || ""}
                  onChange={(e) =>
                    updateEdit(index, { description: e.target.value || null })
                  }
                />
              </div>
              <div className="space-y-2">
                <Label>Priority</Label>
                <select
                  className="flex h-10 w-full rounded-md border border-input bg-white px-3 text-sm"
                  value={draft.priority}
                  onChange={(e) =>
                    updateEdit(index, { priority: e.target.value as TaskPriority })
                  }
                >
                  <option value="p0">P0 — critical</option>
                  <option value="p1">P1 — high</option>
                  <option value="p2">P2 — medium</option>
                  <option value="p3">P3 — low</option>
                </select>
              </div>
              <div className="space-y-2">
                <Label>Due</Label>
                <Input
                  type="datetime-local"
                  value={toLocalInput(draft.due_at)}
                  onChange={(e) => updateEdit(index, { due_at: toIso(e.target.value) })}
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>Guaranteed remind at</Label>
                <Input
                  type="datetime-local"
                  value={toLocalInput(draft.explicit_remind_at)}
                  onChange={(e) =>
                    updateEdit(index, { explicit_remind_at: toIso(e.target.value) })
                  }
                />
              </div>
            </div>
          ))}

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              disabled={confirm.isPending || edits.some((d) => !d.title.trim())}
              onClick={() => confirm.mutate()}
            >
              {confirm.isPending ? "Saving…" : "Confirm & save"}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={reject.isPending}
              onClick={() => reject.mutate()}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setExtraction(null);
                setEdits([]);
              }}
            >
              Edit source text
            </Button>
          </div>
        </div>
      )}

      {error && <p className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
