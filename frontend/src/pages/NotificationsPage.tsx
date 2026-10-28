import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function NotificationsPage() {
  const qc = useQueryClient();
  const notifs = useQuery({ queryKey: ["notifications"], queryFn: () => api.listNotifications() });

  const mark = useMutation({
    mutationFn: (id: string) => api.markRead(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });

  const markAll = useMutation({
    mutationFn: () => api.markAllRead(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-semibold">Notifications</h1>
          <p className="text-muted-foreground">In-app inbox from the reminder engine.</p>
        </div>
        <Button variant="outline" onClick={() => markAll.mutate()} disabled={markAll.isPending}>
          Mark all read
        </Button>
      </div>

      <ul className="space-y-3">
        {(notifs.data || []).length === 0 && (
          <li className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
            No notifications yet. Create a due task and wait for the Celery worker, or trigger evaluate.
          </li>
        )}
        {(notifs.data || []).map((n) => (
          <li
            key={n.id}
            className={`rounded-xl border border-border/80 p-4 ${n.read_at ? "bg-white/50" : "bg-white/90"}`}
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-medium">{n.title}</p>
                <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{n.body}</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  {new Date(n.created_at).toLocaleString()}
                  {n.read_at ? " · read" : " · unread"}
                </p>
              </div>
              {!n.read_at && (
                <Button size="sm" variant="secondary" onClick={() => mark.mutate(n.id)}>
                  Mark read
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
