export type TaskStatus =
  | "pending"
  | "planning"
  | "queued"
  | "running"
  | "waiting_approval"
  | "paused"
  | "scheduled"
  | "completed"
  | "failed"
  | "cancelled";

export interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  phone: string;
  timezone: string;
}

export interface TaskEvent {
  id: string;
  seq: number;
  type: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string | null;
}

export interface PlanStep {
  tool: string;
  args: Record<string, unknown>;
  label: string;
  status: string;
  verified?: boolean;
  error?: string;
  output?: Record<string, unknown>;
  approved?: boolean;
  index: number;
}

export interface Task {
  id: string;
  title: string;
  prompt: string;
  kind: string;
  agent: string;
  status: TaskStatus;
  priority: number;
  progress: number;
  current_step: string;
  source: string;
  error: string;
  approval_required: boolean;
  scheduled_for: string | null;
  recurrence: string;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  plan?: PlanStep[];
  result?: {
    summary?: string[];
    artifacts?: Artifact[];
    verified?: boolean;
    steps?: { tool: string; status: string; verified: boolean }[];
  };
  events?: TaskEvent[];
}

export interface Artifact {
  kind: string;
  title?: string;
  path?: string;
  url?: string;
  task_id?: string;
  content_id?: string;
}

export interface Approval {
  id: string;
  task_id: string | null;
  task_title: string;
  tool: string;
  action: string;
  explanation: string;
  payload: Record<string, unknown>;
  risk: string;
  status: string;
  note: string;
  created_at: string | null;
  decided_at: string | null;
}

export interface ContentItem {
  id: string;
  platform: string;
  kind: string;
  title: string;
  status: string;
  hook: string;
  script: string;
  caption: string;
  hashtags: string;
  description: string;
  metadata: Record<string, unknown>;
  asset_url: string;
  thumb_url: string;
  has_video: boolean;
  task_id: string | null;
  scheduled_for: string | null;
  published_at: string | null;
  external_id: string;
  duration_seconds: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface MemoryItem {
  id: string;
  kind: string;
  title: string;
  content: string;
  tags: string[];
  source: string;
  importance: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface Integration {
  id: string;
  name: string;
  category: string;
  status: "connected" | "needs_auth" | "not_configured" | "error";
  env_configured: boolean;
  env: string[];
  scopes: string[];
  capabilities: string[];
  setup: string[];
  docs: string;
  last_error: string;
  last_sync_at: string | null;
  managed?: boolean;
  managed_handle?: string;
  channel?: "direct" | "managed" | "none";
  effective_status?: Integration["status"];
}

export interface IntegrationPayload {
  integrations: Integration[];
  managed?: {
    configured: boolean;
    profile_username: string;
    connections: Record<string, { handle: string; display_name: string }>;
    platforms: { id: string; name: string; connected: boolean; handle: string; display_name: string }[];
    quota?: {
      available: boolean;
      used: number | null;
      limit: number | null;
      remaining: number | null;
      percent: number;
      resets_at: string;
      plan: string;
      unlimited: boolean;
      level: "ok" | "low" | "exhausted";
      error: string;
    };
    error: string;
  };
  whatsapp: {
    configured: boolean;
    allowed_numbers: string[];
    webhook_url: string;
    signature_enforced: boolean;
  };
  ai: AiCapabilities;
  media: MediaCapabilities;
}

export interface AiCapabilities {
  provider: string;
  model: string;
  configured: boolean;
  offline_mode: boolean;
  note: string;
  tts: boolean;
  images: boolean;
}

export interface MediaCapabilities {
  ffmpeg: boolean;
  ffmpeg_binary: string;
  font: string;
  tts: boolean;
  ai_images: boolean;
}

export interface WorkerStatus {
  alive: boolean;
  started_at: string | null;
  last_tick: string | null;
  running: number;
  concurrency: number;
  processed: number;
  last_error: string;
}

export interface Overview {
  stats: {
    total: number;
    active: number;
    completed_week: number;
    failed_week: number;
    pending_approvals: number;
    unread_notifications: number;
    content_drafts: number;
  };
  status_counts: Record<string, number>;
  daily: { date: string; created: number; completed: number }[];
  recent_tasks: Task[];
  upcoming: Task[];
  latest_content: ContentItem[];
  system: {
    worker: WorkerStatus;
    queue_depth: number;
    ai: AiCapabilities;
    media: MediaCapabilities;
    realtime_subscribers: number;
    storage: { workspace_bytes: number; free_bytes: number; database_url_kind: string };
    integrations: { id: string; name: string; status: string }[];
  };
}

export interface NotificationItem {
  id: string;
  title: string;
  body: string;
  level: string;
  read: boolean;
  channel: string;
  meta: Record<string, unknown>;
  created_at: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  kind: string;
  prompt: string;
  schedule_kind: string;
  at_time: string;
  interval_minutes: number;
  enabled: boolean;
  publishing_mode: string;
  config: Record<string, unknown>;
  last_run_at: string | null;
  next_run_at: string | null;
}

export interface LogEntry {
  id: string;
  actor: string;
  action: string;
  target: string;
  level: string;
  ip: string;
  data: Record<string, unknown>;
  created_at: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  task_id: string | null;
  source: string;
  created_at: string | null;
}

export interface FileEntry {
  name: string;
  path: string;
  type: "file" | "dir";
  size: number;
  modified: string;
  previewable?: boolean;
}

export interface ToolSpec {
  name: string;
  description: string;
  category: string;
  risk: "safe" | "confirm" | "blocked";
  requires: string[];
  params: Record<string, { type?: string; required?: boolean; description?: string }>;
}

export interface SettingsMap {
  auto_approve: string[];
  disabled_tools: string[];
  publishing_mode: "draft" | "approval" | "auto";
  max_daily_tasks: number;
  daily_ai_budget_usd: number;
  notify_on_complete: boolean;
  whatsapp_notifications: boolean;
  research_depth: string;
  voice_enabled: boolean;
  default_video_format: string;
  default_language: string;
  allowed_dirs: string[];
  [key: string]: unknown;
}

export interface CalendarEvent {
  id?: string;
  summary: string;
  start: string;
  end: string;
  location?: string;
  attendees?: string[];
  html_link?: string;
}

export interface EmailMessage {
  id: string;
  thread_id?: string;
  subject: string;
  from: string;
  date: string;
  snippet: string;
  labels?: string[];
}

export interface DesktopJob {
  id: string;
  command: string;
  cwd: string;
  status: string;
  output: string;
  exit_code: number | null;
  created_at: string | null;
  finished_at: string | null;
}
