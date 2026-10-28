const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

export type TaskStatus = "todo" | "in_progress" | "done" | "cancelled";
export type TaskPriority = "p0" | "p1" | "p2" | "p3";

export interface User {
  id: string;
  email: string;
  timezone: string;
  created_at: string;
}

export interface Task {
  id: string;
  user_id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  due_at: string | null;
  completed_at: string | null;
  source: string;
  explicit_remind_at: string | null;
  force_within_quiet: boolean;
  last_notified_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface Preferences {
  id: string;
  user_id: string;
  quiet_start: string;
  quiet_end: string;
  channels: string[];
  digest_enabled: boolean;
  digest_time: string;
  min_score_threshold: number;
  timezone: string;
  updated_at: string;
}

export interface InAppNotification {
  id: string;
  title: string;
  body: string;
  read_at: string | null;
  related_decision_id: string | null;
  created_at: string;
}

function authHeaders(): HeadersInit {
  const token = localStorage.getItem("nudge_token");
  return {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers || {}) },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore */
    }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  register: (email: string, password: string, timezone = "UTC") =>
    request<{ access_token: string }>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, timezone }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<User>("/auth/me"),
  listTasks: (params?: { status?: string }) => {
    const q = params?.status ? `?status=${params.status}` : "";
    return request<Task[]>(`/tasks${q}`);
  },
  createTask: (body: Partial<Task> & { title: string }) =>
    request<Task>("/tasks", { method: "POST", body: JSON.stringify(body) }),
  updateTask: (id: string, body: Partial<Task>) =>
    request<Task>(`/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteTask: (id: string) => request<void>(`/tasks/${id}`, { method: "DELETE" }),
  getPreferences: () => request<Preferences>("/preferences"),
  updatePreferences: (body: Partial<Preferences>) =>
    request<Preferences>("/preferences", { method: "PATCH", body: JSON.stringify(body) }),
  listNotifications: (unreadOnly = false) =>
    request<InAppNotification[]>(`/notifications/in-app?unread_only=${unreadOnly}`),
  markRead: (id: string) =>
    request<InAppNotification>(`/notifications/in-app/${id}/read`, { method: "POST" }),
  markAllRead: () =>
    request<{ updated: number }>("/notifications/in-app/read-all", { method: "POST" }),
};
