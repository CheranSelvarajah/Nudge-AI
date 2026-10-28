import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { api, type Task } from "@/lib/api";

function priorityLabel(p: Task["priority"]) {
  return p.toUpperCase();
}

function dueLabel(due: string | null) {
  if (!due) return "No due date";
  return new Date(due).toLocaleString();
}

export function DashboardPage() {
  const tasks = useQuery({ queryKey: ["tasks"], queryFn: () => api.listTasks() });
  const notifs = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => api.listNotifications(true),
  });

  const open = (tasks.data || []).filter((t) => t.status === "todo" || t.status === "in_progress");
  const overdue = open.filter((t) => t.due_at && new Date(t.due_at) < new Date());
  const upcoming = open
    .filter((t) => t.due_at && new Date(t.due_at) >= new Date())
    .sort((a, b) => new Date(a.due_at!).getTime() - new Date(b.due_at!).getTime())
    .slice(0, 5);

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold">Dashboard</h1>
          <p className="text-muted-foreground">Open work, due soon, and unread nudges.</p>
        </div>
        <Button asChild>
          <Link to="/tasks">Manage tasks</Link>
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Open tasks" value={open.length} />
        <Stat label="Overdue" value={overdue.length} />
        <Stat label="Unread nudges" value={(notifs.data || []).length} />
      </div>

      <section>
        <h2 className="mb-3 font-display text-xl font-medium">Upcoming</h2>
        <ul className="divide-y divide-border rounded-xl border border-border/80 bg-white/80">
          {upcoming.length === 0 && (
            <li className="px-4 py-6 text-sm text-muted-foreground">No upcoming due dates.</li>
          )}
          {upcoming.map((task) => (
            <li key={task.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <div>
                <p className="font-medium">{task.title}</p>
                <p className="text-xs text-muted-foreground">
                  {priorityLabel(task.priority)} · {dueLabel(task.due_at)}
                  {task.last_notified_at ? " · nudged" : ""}
                </p>
              </div>
              <span className="rounded-md bg-secondary px-2 py-1 text-xs">{task.status}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-border/80 bg-white/80 px-4 py-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 font-display text-3xl font-semibold text-primary">{value}</p>
    </div>
  );
}
