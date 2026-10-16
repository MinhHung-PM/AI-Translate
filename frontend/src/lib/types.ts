// Mirrors backend/app/schemas/api.py. Keep in sync with the OpenAPI contract.

export type Language = "ja" | "vi" | "en";
export type GlobalRole = "member" | "project_manager" | "division_manager" | "admin";
export type ProjectRole = "member" | "manager";
export type MeetingType = "client_meeting" | "internal" | "requirements" | "review" | "steering" | "standup" | "other";
export type MeetingPlatform = "manual_import" | "teams" | "zoom" | "google_meet";
export type MeetingStatus = "planned" | "transcript_ready" | "memo_draft" | "completed" | "archived";
export type MemoStatus = "generating" | "failed" | "draft" | "in_review" | "approved" | "rejected";
export type TranslationStatus = "pending" | "processing" | "done" | "failed";
export type VerificationStatus = "draft" | "needs_review" | "confirmed" | "rejected";
export type Confidence = "high" | "medium" | "low";
export type Priority = "low" | "medium" | "high" | "critical";
export type ActionStatus = "open" | "in_progress" | "blocked" | "done" | "cancelled";
export type IssueStatus = "open" | "monitoring" | "resolved";
export type Likelihood = "low" | "medium" | "high" | "unknown";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type KeyStorage = "none" | "session" | "persistent";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  role: GlobalRole;
  is_active: boolean;
  locale: string;
}

export interface SessionInfo {
  user: User;
  csrf_token: string;
  auth_mode: "dev" | "oidc";
  expires_at: string;
  features: Record<string, boolean>;
}

export interface Project {
  id: string;
  code: string;
  name: string;
  description: string | null;
  client_name: string | null;
  division_id: string | null;
  status: "active" | "archived";
  retention_days: number;
  default_source_language: Language;
  default_target_language: Language;
  default_memo_language: Language;
  translation_instructions: string | null;
  created_at: string;
  my_role: ProjectRole | null;
  permissions: Record<string, boolean>;
}

export interface Member {
  user_id: string;
  email: string;
  display_name: string;
  role: ProjectRole;
}

export interface GlossaryEntry {
  id: string;
  project_id: string;
  source_term: string;
  preferred_translation: string;
  source_language: Language;
  target_language: Language;
  context: string | null;
  is_active: boolean;
}

export interface Participant {
  id: string;
  display_name: string;
  organization: string | null;
  role_label: string | null;
}

export interface Meeting {
  id: string;
  project_id: string;
  project_name: string | null;
  title: string;
  meeting_type: MeetingType;
  scheduled_at: string;
  timezone: string;
  platform: MeetingPlatform;
  platform_status: "available" | "not_configured" | "not_linked";
  meeting_url: string | null;
  objective: string | null;
  custom_instructions: string | null;
  source_language: Language | null;
  detected_language: Language | null;
  target_language: Language;
  memo_language: Language;
  status: MeetingStatus;
  created_by_id: string | null;
  created_at: string;
  content_purged_at: string | null;
  participants: Participant[];
  memo_status: MemoStatus | null;
  entry_count: number;
  permissions: Record<string, boolean>;
}

export interface Translation {
  id: string;
  target_language: Language;
  text: string | null;
  status: TranslationStatus;
  error_message: string | null;
  ambiguity_note: string | null;
  provider: string | null;
  model: string | null;
  is_user_edited: boolean;
  updated_at: string;
}

export interface TranscriptEntry {
  id: string;
  meeting_id: string;
  sequence: number;
  speaker_label: string | null;
  start_ms: number | null;
  end_ms: number | null;
  original_text: string;
  source_language: Language | null;
  original_edited: boolean;
  source_metadata: Record<string, unknown>;
  translation: Translation | null;
}

export interface TranslationStats {
  total: number;
  done: number;
  failed: number;
  pending: number;
  processing: number;
}

export interface Job {
  id: string;
  kind: "translate" | "generate_memo" | "replay" | "fetch_transcript" | "realtime_ingest";
  status: JobStatus;
  meeting_id: string | null;
  progress_done: number;
  progress_total: number;
  attempts: number;
  error_code: string | null;
  error_message: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface LiveSession {
  id: string;
  meeting_id: string;
  connector: string;
  is_demo: boolean;
  status: "running" | "completed" | "failed" | "stopped" | "waiting" | "interrupted";
  provider_session_id?: string | null;
  reconnect_count?: number;
  last_event_at?: string | null;
  status_message?: string | null;
  capture_config?: { sources: AudioSourceConfig[]; translate: boolean; stt_model: string; mode?: "streaming" | "chunked"; languages?: Language[] } | null;
  entries_total: number;
  entries_emitted: number;
  started_at: string;
  ended_at: string | null;
  job_id: string | null;
}

export interface SourceRef {
  entry_id: string;
  sequence: number;
  speaker_label: string | null;
  start_ms: number | null;
  excerpt: string | null;
}

interface ItemBase {
  id: string;
  memo_id: string;
  meeting_id: string;
  project_id: string;
  code: string;
  verification_status: VerificationStatus;
  ai_generated: boolean;
  confidence: Confidence | null;
  review_note: string | null;
  owner_text: string | null;
  owner_user_id: string | null;
  sort_order: number;
  sources: SourceRef[];
}

export interface Decision extends ItemBase {
  statement: string;
}

export interface Issue extends ItemBase {
  description: string;
  impact: string | null;
  status: IssueStatus;
  priority: Priority;
  follow_up: string | null;
}

export interface Risk extends ItemBase {
  description: string;
  probability: Likelihood;
  impact: string | null;
  severity: Priority;
  mitigation: string | null;
}

export interface ActionItem extends ItemBase {
  description: string;
  due_date: string | null;
  due_text: string | null;
  due_needs_confirmation: boolean;
  priority: Priority;
  status: ActionStatus;
  related_decision_id: string | null;
  related_issue_id: string | null;
  completed_at: string | null;
  is_overdue: boolean;
  meeting_title: string | null;
  project_name: string | null;
}

export interface DiscussionTopic {
  topic: string;
  points: string[];
  source_entry_ids: string[];
}

export interface OpenQuestion {
  question: string;
  source_entry_ids: string[];
}

export interface NextMeeting {
  when_text: string | null;
  agenda: string[];
  source_entry_ids: string[];
}

export type PMBasis = "evidence" | "ai_suggestion" | "human";

export interface PMAssessment {
  assessment: string;
  basis: PMBasis;
  source_entry_ids: string[];
}

export const PM_KEYS = ["schedule", "scope", "quality", "cost", "customer_satisfaction", "escalation"] as const;
export type PMKey = (typeof PM_KEYS)[number];
export type PMView = Partial<Record<PMKey, PMAssessment | null>>;

export interface Memo {
  id: string;
  meeting_id: string;
  language: Language;
  status: MemoStatus;
  executive_summary: string;
  discussion: DiscussionTopic[];
  open_questions: OpenQuestion[];
  next_meeting: NextMeeting | null;
  pm_view: PMView | null;
  generation_error: string | null;
  prompt_version: string | null;
  provider: string | null;
  model: string | null;
  generated_at: string | null;
  generation_count: number;
  reviewed_by_id: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
  updated_at: string;
  meeting_info: {
    title: string;
    project_name: string;
    scheduled_at: string;
    timezone: string;
    participants: string[];
    objective: string | null;
    source_language: Language | null;
    memo_language: Language;
  };
  decisions: Decision[];
  action_items: ActionItem[];
  issues: Issue[];
  risks: Risk[];
  unreviewed_items: number;
  permissions: Record<string, boolean>;
}

export interface ProviderModel {
  id: string;
  label: string | null;
  input_per_1m: string | null;
  output_per_1m: string | null;
}

export interface ProviderCatalogEntry {
  key: string;
  display_name: string;
  requires_api_key: boolean;
  allow_custom_base_url: boolean;
  allow_custom_model: boolean;
  dev_only: boolean;
  capabilities: string[];
  models: ProviderModel[];
}

export interface ProviderSettings {
  providers: ProviderCatalogEntry[];
  secret_storage_available: boolean;
  remember_key_supported: boolean;
}

export interface ProviderConfig {
  id: string;
  provider: string;
  model: string;
  base_url: string | null;
  is_default: boolean;
  key_storage: KeyStorage;
  key_hint: string | null;
  has_usable_key: boolean;
  key_updated_at: string | null;
  last_test_ok: boolean | null;
  last_test_message: string | null;
  last_tested_at: string | null;
}

export interface UsageSummary {
  total_requests: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost_usd: string;
  failed_requests: number;
  processing_ms: number;
  requests_with_estimated_tokens: number;
  by_model: { provider: string; model: string; requests: number; estimated_cost_usd: string }[];
  by_operation: { operation: string; requests: number; failed: number; estimated_cost_usd: string }[];
  by_project: { project_id: string; project_name: string; requests: number; estimated_cost_usd: string }[];
  by_meeting: { meeting_id: string; meeting_title: string; requests: number; estimated_cost_usd: string }[];
  cost_note: string;
}

export interface Dashboard {
  total_meetings: number;
  drafts_awaiting_review: number;
  open_action_items: number;
  overdue_action_items: number;
  unconfirmed_action_items: number;
  high_priority_issues: { id: string; code: string; description: string; priority: Priority; meeting_id: string; meeting_title: string }[];
  high_priority_risks: { id: string; code: string; description: string; severity: Priority; meeting_id: string; meeting_title: string }[];
  recent_meetings: { id: string; title: string; scheduled_at: string; status: MeetingStatus; project_name: string; memo_status: MemoStatus | null }[];
  recent_activity: { action: string; created_at: string; resource_type: string; resource_id: string | null; project_name: string; actor: string | null }[];
  usage: { total_requests: number; estimated_cost_usd: string; failed_requests: number };
}

export interface ConnectorStatus {
  key: string;
  display_name: string;
  state: "available" | "demo" | "not_configured";
  message: string;
  supports_live: boolean;
  supports_transcript_import: boolean;
}

export interface Division {
  id: string;
  name: string;
  description: string | null;
}

export interface DivisionAssignment {
  id: string;
  user_id: string;
  division_id: string;
  can_view_transcripts: boolean;
}

export interface AuditEvent {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  project_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

// ---- Workstream 2: platform integrations (mirrors backend app/api/v1/integrations.py) ----

export type PlatformProvider = "teams" | "zoom" | "google_meet";
export type CapabilityName =
  | "transcript_import"
  | "list_meetings"
  | "post_meeting_transcript"
  | "live_transcript"
  | "live_audio"
  | "speaker_metadata"
  | "meeting_event_notifications"
  | "recovery_after_disconnect";
export type CapabilityStatusName =
  | "available"
  | "requires_configuration"
  | "requires_user_consent"
  | "requires_admin_approval"
  | "not_supported"
  | "temporarily_unavailable";
export type ConnectionDisplayStatus =
  | "not_configured"
  | "not_connected"
  | "awaiting_authorization"
  | "connected"
  | "connected_post_meeting_only"
  | "admin_approval_required"
  | "temporarily_disconnected"
  | "error";

export interface CapabilityState {
  capability: CapabilityName;
  status: CapabilityStatusName;
  message: string;
  remediation: string | null;
  verified_live: boolean;
}

export interface ConnectionView {
  provider: PlatformProvider;
  display_name: string;
  configured: boolean;
  configuration_problems: string[];
  sandbox: boolean;
  status: ConnectionDisplayStatus;
  account: string | null;
  granted_scopes: string[];
  requested_scopes: string[];
  capabilities: CapabilityState[];
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_event_at: string | null;
  last_error_category: string | null;
  last_error_message: string | null;
  reconnect_count: number;
  redirect_uri: string | null;
}

export interface AvailableMeeting {
  provider_meeting_id: string;
  title: string;
  start: string | null;
  end: string | null;
  join_url: string | null;
  has_transcript: boolean | null;
}

export type ExternalTranscriptStatus = "unknown" | "pending" | "available" | "imported" | "not_available" | "permission_denied" | "failed";

export interface ExternalSource {
  id: string;
  meeting_id: string;
  provider: PlatformProvider;
  provider_meeting_id: string;
  join_url: string | null;
  transcript_status: ExternalTranscriptStatus;
  status_message: string | null;
  fetch_attempts: number;
  last_checked_at: string | null;
  next_check_at: string | null;
  live_requested: boolean;
  sandbox: boolean;
  capabilities: CapabilityState[];
  connection_status: ConnectionDisplayStatus;
  live_session: LiveSession | null;
}

export interface ProviderEventRow {
  provider: string;
  event_type: string;
  status: string;
  detail: string | null;
  meeting_id: string | null;
  received_at: string;
}

export interface IntegrationDiagnostics {
  connection: ConnectionView;
  recent_events: ProviderEventRow[];
  recent_jobs: Job[];
}

// ---- Live audio capture (mirrors backend app/api/v1/audio.py) ----
export interface AudioSourceConfig {
  id: string;
  kind: "microphone" | "system" | "tab" | "device";
  label: string;
  single_speaker: boolean;
}

export interface AudioSpeaker {
  speaker_key: string;
  source_id: string;
  display_name: string;
  segments: number;
  has_voice_reference: boolean;
}

export interface AudioSession {
  session: LiveSession;
  speakers: AudioSpeaker[];
}

export interface AudioChunkResult {
  entries: TranscriptEntry[];
  duplicate: boolean;
  note: string | null;
}
