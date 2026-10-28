import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";

const schema = z.object({
  quiet_start: z.string(),
  quiet_end: z.string(),
  digest_time: z.string(),
  digest_enabled: z.boolean(),
  timezone: z.string().min(1),
  min_score_threshold: z.coerce.number().min(0).max(1),
  channel_in_app: z.boolean(),
  channel_email: z.boolean(),
});

type FormValues = z.infer<typeof schema>;

function trimTime(value: string) {
  // API may return HH:MM:SS
  return value.slice(0, 5);
}

export function SettingsPage() {
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: ["preferences"], queryFn: () => api.getPreferences() });
  const form = useForm<FormValues>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (!prefs.data) return;
    form.reset({
      quiet_start: trimTime(prefs.data.quiet_start),
      quiet_end: trimTime(prefs.data.quiet_end),
      digest_time: trimTime(prefs.data.digest_time),
      digest_enabled: prefs.data.digest_enabled,
      timezone: prefs.data.timezone,
      min_score_threshold: prefs.data.min_score_threshold,
      channel_in_app: prefs.data.channels.includes("in_app"),
      channel_email: prefs.data.channels.includes("email"),
    });
  }, [prefs.data, form]);

  const save = useMutation({
    mutationFn: (values: FormValues) => {
      const channels: string[] = [];
      if (values.channel_in_app) channels.push("in_app");
      if (values.channel_email) channels.push("email");
      if (channels.length === 0) channels.push("in_app");
      return api.updatePreferences({
        quiet_start: values.quiet_start.length === 5 ? `${values.quiet_start}:00` : values.quiet_start,
        quiet_end: values.quiet_end.length === 5 ? `${values.quiet_end}:00` : values.quiet_end,
        digest_time: values.digest_time.length === 5 ? `${values.digest_time}:00` : values.digest_time,
        digest_enabled: values.digest_enabled,
        timezone: values.timezone,
        min_score_threshold: values.min_score_threshold,
        channels,
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["preferences"] }),
  });

  if (prefs.isLoading) return <p className="text-muted-foreground">Loading preferences…</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-3xl font-semibold">Settings</h1>
        <p className="text-muted-foreground">Quiet hours, channels, digest, and timezone.</p>
      </div>

      <form
        className="max-w-xl space-y-4 rounded-xl border border-border/80 bg-white/80 p-5"
        onSubmit={form.handleSubmit((v) => save.mutate(v))}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="quiet_start">Quiet start</Label>
            <Input id="quiet_start" type="time" {...form.register("quiet_start")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="quiet_end">Quiet end</Label>
            <Input id="quiet_end" type="time" {...form.register("quiet_end")} />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="timezone">Timezone</Label>
          <Input id="timezone" {...form.register("timezone")} />
        </div>
        <div className="space-y-2">
          <Label htmlFor="digest_time">Digest time</Label>
          <Input id="digest_time" type="time" {...form.register("digest_time")} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...form.register("digest_enabled")} />
          Enable digests for mid-score reminders
        </label>
        <div className="space-y-2">
          <Label htmlFor="min_score_threshold">Min score threshold</Label>
          <Input
            id="min_score_threshold"
            type="number"
            step="0.05"
            min={0}
            max={1}
            {...form.register("min_score_threshold")}
          />
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">Channels</p>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...form.register("channel_in_app")} />
            In-app
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" {...form.register("channel_email")} />
            Email (console stub by default)
          </label>
        </div>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save preferences"}
        </Button>
        {save.isSuccess && <p className="text-sm text-primary">Saved.</p>}
      </form>
    </div>
  );
}
