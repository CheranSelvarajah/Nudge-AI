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

function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** Wall-clock parts of an instant in an IANA zone (DST-aware). */
function wallParts(ms: number, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(ms));
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    hour: Number(get("hour")),
    minute: Number(get("minute")),
  };
}

/** Show ISO due times as datetime-local wall clock in the extraction timezone. */
function toLocalInput(iso: string | null | undefined, timeZone = browserTimeZone()): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const w = wallParts(d.getTime(), timeZone);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${w.year}-${pad(w.month)}-${pad(w.day)}T${pad(w.hour)}:${pad(w.minute)}`;
}

/** Interpret datetime-local as wall time in timeZone → UTC ISO. */
function toIso(local: string, timeZone = browserTimeZone()): string | null {
  if (!local) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local);
  if (!match) return null;
  const y = Number(match[1]);
  const mo = Number(match[2]);
  const day = Number(match[3]);
  const hh = Number(match[4]);
  const mm = Number(match[5]);
  // Guess UTC then nudge until wall parts in timeZone match (handles DST).
  let guess = Date.UTC(y, mo - 1, day, hh, mm, 0);
  for (let i = 0; i < 4; i++) {
    const w = wallParts(guess, timeZone);
    const asUtc = Date.UTC(w.year, w.month - 1, w.day, w.hour, w.minute, 0);
    const target = Date.UTC(y, mo - 1, day, hh, mm, 0);
    const delta = target - asUtc;
    if (delta === 0) break;
    guess += delta;
  }
  return new Date(guess).toISOString();
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

function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message;
  if (typeof err === "string" && err.trim()) return err;
  return "Extract failed. Check that you are logged in and the API is running.";
}

export function NlTaskIntake() {
  const qc = useQueryClient();
  const timeZone = browserTimeZone();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<ExtractResponse | null>(null);
  const [edits, setEdits] = useState<ConfirmDraft[]>([]);

  const extract = useMutation({
    mutationFn: () =>
      api.extractTasks({
        text,
        timezone: timeZone,
      }),
    onSuccess: (data) => {
      if (!data?.drafts?.length) {
        setExtraction(null);
        setEdits([]);
        setError(
          "Extraction returned no drafts. With no OPENAI_API_KEY the stub should still return one — check API logs.",
        );
        return;
      }
      setError(null);
      setExtraction(data);
      setEdits(data.drafts.map(draftToEditable));
    },
    onError: (err: unknown) => setError(errorMessage(err)),
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
    onError: (err: unknown) => setError(errorMessage(err)),
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
    onError: (err: unknown) => setError(errorMessage(err)),
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
        <p className="mt-1 text-xs text-muted-foreground">
          No OpenAI key needed for local use: the API falls back to a deterministic stub when{" "}
          <code className="rounded bg-muted px-1">OPENAI_API_KEY</code> is empty.
        </p>
      </div>

      {error && (
        <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}

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
            onClick={() => {
              setError(null);
              extract.mutate();
            }}
          >
            {extract.isPending ? "Extracting…" : "Extract draft"}
          </Button>
          {extract.isPending && (
            <p className="text-xs text-muted-foreground">Calling /api/nl/extract…</p>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-md border border-primary/30 bg-primary/5 px-3 py-2">
            <p className="font-medium text-sm">Review draft before saving</p>
            <p className="text-xs text-muted-foreground">
              Proposal <span className="font-mono">{String(extraction.proposal_id).slice(0, 8)}</span> ·
              provider <span className="font-medium">{extraction.llm_provider}</span>
              {extraction.notes ? ` · ${extraction.notes}` : ""}
            </p>
          </div>

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
                  value={toLocalInput(draft.due_at, timeZone)}
                  onChange={(e) =>
                    updateEdit(index, { due_at: toIso(e.target.value, timeZone) })
                  }
                />
              </div>
              <div className="space-y-2 md:col-span-2">
                <Label>Guaranteed remind at</Label>
                <Input
                  type="datetime-local"
                  value={toLocalInput(draft.explicit_remind_at, timeZone)}
                  onChange={(e) =>
                    updateEdit(index, {
                      explicit_remind_at: toIso(e.target.value, timeZone),
                    })
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
    </section>
  );
}
