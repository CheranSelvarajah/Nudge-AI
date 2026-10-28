import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, type Task, type TaskPriority, type TaskStatus } from "@/lib/api";

const schema = z.object({
  title: z.string().min(1),
  description: z.string().optional(),
  priority: z.enum(["p0", "p1", "p2", "p3"]),
  due_at: z.string().optional(),
  explicit_remind_at: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

function toIso(local: string | undefined) {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function TasksPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("");
  const tasks = useQuery({
    queryKey: ["tasks", statusFilter],
    queryFn: () => api.listTasks(statusFilter ? { status: statusFilter } : undefined),
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { priority: "p2" },
  });

  const create = useMutation({
    mutationFn: (values: FormValues) =>
      api.createTask({
        title: values.title,
        description: values.description || null,
        priority: values.priority as TaskPriority,
        due_at: toIso(values.due_at),
        explicit_remind_at: toIso(values.explicit_remind_at),
      } as Partial<Task> & { title: string }),
    onSuccess: () => {
      form.reset({ priority: "p2", title: "", description: "" });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });

  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Task> }) => api.updateTask(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteTask(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="font-display text-3xl font-semibold">Tasks</h1>
        <p className="text-muted-foreground">Create, filter, and update work items.</p>
      </div>

      <form
        className="grid gap-4 rounded-xl border border-border/80 bg-white/80 p-5 md:grid-cols-2"
        onSubmit={form.handleSubmit((v) => create.mutate(v))}
      >
        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="title">Title</Label>
          <Input id="title" {...form.register("title")} placeholder="What needs doing?" />
        </div>
        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="description">Description</Label>
          <Textarea id="description" {...form.register("description")} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="priority">Priority</Label>
          <select
            id="priority"
            className="flex h-10 w-full rounded-md border border-input bg-white px-3 text-sm"
            {...form.register("priority")}
          >
            <option value="p0">P0 — critical</option>
            <option value="p1">P1 — high</option>
            <option value="p2">P2 — medium</option>
            <option value="p3">P3 — low</option>
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="due_at">Due</Label>
          <Input id="due_at" type="datetime-local" {...form.register("due_at")} />
        </div>
        <div className="space-y-2 md:col-span-2">
          <Label htmlFor="explicit_remind_at">Guaranteed remind at (optional)</Label>
          <Input id="explicit_remind_at" type="datetime-local" {...form.register("explicit_remind_at")} />
        </div>
        <div className="md:col-span-2">
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Adding…" : "Add task"}
          </Button>
        </div>
      </form>

      <div className="flex flex-wrap items-center gap-2">
        <Label>Filter</Label>
        {["", "todo", "in_progress", "done", "cancelled"].map((s) => (
          <Button
            key={s || "all"}
            size="sm"
            variant={statusFilter === s ? "default" : "outline"}
            onClick={() => setStatusFilter(s)}
          >
            {s || "all"}
          </Button>
        ))}
      </div>

      <ul className="space-y-3">
        {(tasks.data || []).map((task) => (
          <li
            key={task.id}
            className="flex flex-col gap-3 rounded-xl border border-border/80 bg-white/80 p-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <p className="font-medium">{task.title}</p>
              <p className="text-xs text-muted-foreground">
                {task.priority.toUpperCase()}
                {task.due_at ? ` · due ${new Date(task.due_at).toLocaleString()}` : ""}
                {task.explicit_remind_at
                  ? ` · remind ${new Date(task.explicit_remind_at).toLocaleString()}`
                  : ""}
                {task.last_notified_at ? " · last nudged" : ""}
              </p>
              {task.description && <p className="mt-1 text-sm text-muted-foreground">{task.description}</p>}
            </div>
            <div className="flex flex-wrap gap-2">
              <select
                className="h-8 rounded-md border border-input bg-white px-2 text-xs"
                value={task.status}
                onChange={(e) =>
                  update.mutate({ id: task.id, body: { status: e.target.value as TaskStatus } })
                }
              >
                <option value="todo">todo</option>
                <option value="in_progress">in_progress</option>
                <option value="done">done</option>
                <option value="cancelled">cancelled</option>
              </select>
              <Button size="sm" variant="destructive" onClick={() => remove.mutate(task.id)}>
                Delete
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
