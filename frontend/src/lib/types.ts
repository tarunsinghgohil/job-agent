/**
 * Shapes for every entity in docs/API_CONTRACT.md.
 *
 * Fields the backend stores as free-form JSON are typed as `JsonValue` /
 * `Record<string, JsonValue>` rather than `any` so call sites must narrow.
 */

export type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export type JsonObject = { [key: string]: JsonValue };

export interface ApiErrorBody {
  error: { code: string; message: string; details?: JsonObject };
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/* ------------------------------------------------------------------ enums */

export type JobStatus = "new" | "qualified" | "rejected" | "queued" | "applied" | "archived";
export const JOB_STATUSES: JobStatus[] = [
  "new",
  "qualified",
  "rejected",
  "queued",
  "applied",
  "archived",
];

export type MatchDecision = "HIGH_PRIORITY" | "REVIEW" | "REJECT";
export const MATCH_DECISIONS: MatchDecision[] = ["HIGH_PRIORITY", "REVIEW", "REJECT"];

export type ApplicationStatus =
  | "pending_review"
  | "approved"
  | "prepared"
  | "submitted"
  | "rejected"
  | "failed"
  | "withdrawn"
  | "interview"
  | "offer"
  | "closed";
export const APPLICATION_STATUSES: ApplicationStatus[] = [
  "pending_review",
  "approved",
  "prepared",
  "submitted",
  "interview",
  "offer",
  "rejected",
  "failed",
  "withdrawn",
  "closed",
];

export type AnswerState = "verified" | "inferred" | "needs_review";
export const ANSWER_STATES: AnswerState[] = ["verified", "inferred", "needs_review"];

export type RuleOperator =
  | "contains"
  | "not_contains"
  | "equals"
  | "not_equals"
  | "in"
  | "not_in"
  | "gte"
  | "lte"
  | "gt"
  | "lt"
  | "between"
  | "regex";
export const RULE_OPERATORS: RuleOperator[] = [
  "contains",
  "not_contains",
  "equals",
  "not_equals",
  "in",
  "not_in",
  "gte",
  "lte",
  "gt",
  "lt",
  "between",
  "regex",
];

export type RuleField =
  | "title"
  | "company"
  | "location"
  | "description"
  | "industry"
  | "employment_type"
  | "salary_lpa"
  | "experience_min"
  | "experience_max"
  | "source"
  | "remote"
  | "skills";
export const RULE_FIELDS: RuleField[] = [
  "title",
  "company",
  "location",
  "description",
  "industry",
  "employment_type",
  "salary_lpa",
  "experience_min",
  "experience_max",
  "source",
  "remote",
  "skills",
];

export type SourceHealth = "unknown" | "healthy" | "degraded" | "failing" | "disabled";

export type AgentRunStatus =
  | "pending"
  | "running"
  | "success"
  | "partial"
  | "failed"
  | "cancelled";

export type NotificationChannelType = "email" | "telegram" | "slack" | "whatsapp";

export type NotificationEventType =
  | "high_match_job"
  | "daily_digest"
  | "application_ready"
  | "application_submitted"
  | "integration_failed"
  | "scheduled_run_failed"
  | "interview_added"
  | "followup_due"
  | "quota_warning"
  | "weekly_summary";

export type NotificationStatus = "pending" | "sent" | "failed" | "suppressed";

export type ApplicationChannel = "manual" | "email" | "ats" | "linkedin" | "company_portal";
export const APPLICATION_CHANNELS: ApplicationChannel[] = [
  "manual",
  "email",
  "ats",
  "linkedin",
  "company_portal",
];

export type AssetType = "resume" | "cover_letter" | "portfolio_note" | "pitch";

export type EvidenceKind =
  | "experience"
  | "project"
  | "skill"
  | "education"
  | "certification"
  | "summary";

/* ----------------------------------------------------------------- identity */

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_owner: boolean;
  last_login_at: string | null;
  created_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface RefreshResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user?: User;
}

export interface UserSession {
  id: string;
  user_agent: string;
  ip_address: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
  is_current?: boolean;
}

/* ------------------------------------------------------------------ profile */

export interface Experience {
  id: string;
  company: string;
  title: string;
  employment_type: string;
  location: string;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  description: string;
  highlights: string[];
  tech_stack: string[];
  sort_order: number;
}

export interface Project {
  id: string;
  name: string;
  role: string;
  description: string;
  url: string;
  tech_stack: string[];
  highlights: string[];
  sort_order: number;
}

export interface Education {
  id: string;
  institution: string;
  degree: string;
  field_of_study: string;
  start_year: number | null;
  end_year: number | null;
  grade: string;
  sort_order: number;
}

export interface ProfileSkill {
  id: string;
  skill_id?: string;
  name: string;
  slug?: string;
  category?: string;
  years: number | null;
  proficiency: string;
  is_primary: boolean;
  evidence_note: string;
}

export interface CareerFact {
  id: string;
  kind: string;
  statement: string;
  detail: string;
  source_ref: string;
  confidence: number;
  is_verified: boolean;
  tags: string[];
}

export interface Profile {
  id: string;
  full_name: string;
  headline: string;
  summary: string;
  email: string;
  phone: string;
  location: string;
  links: Record<string, string>;
  total_experience_years: number;
  domains: string[];
  preferred_roles: string[];
  preferred_industries: string[];
  notice_period: string;
  current_ctc_lpa: number | null;
  expected_ctc_lpa: number | null;
  work_authorization: boolean;
  work_authorization_note: string;
  open_to_relocation: boolean;
  experiences?: Experience[];
  projects?: Project[];
  education?: Education[];
  skills?: ProfileSkill[];
  facts?: CareerFact[];
}

/* -------------------------------------------------------------- preferences */

export interface Preferences {
  id?: string;
  target_roles: string[];
  preferred_locations: string[];
  remote_ok: boolean;
  remote_only: boolean;
  min_salary_lpa: number | null;
  target_salary_lpa: number | null;
  currency: string;
  experience_min_years: number | null;
  experience_max_years: number | null;
  notice_period_days: number;
  employment_types: string[];
  company_types: string[];
  industries: string[];
  preferred_companies: string[];
  excluded_companies: string[];
  must_have_keywords: string[];
  nice_to_have_keywords: string[];
  excluded_keywords: string[];
  review_threshold: number;
  high_priority_threshold: number;
  scoring_weights: Record<string, number>;
  daily_application_cap: number;
  approval_required: boolean;
  auto_submit_enabled: boolean;
  discovery_schedule_cron: string;
  timezone: string;
  semantic_scoring_enabled: boolean;
  semantic_weight: number;
}

export interface MatchRule {
  id: string;
  name: string;
  field: string;
  operator: string;
  value: JsonValue;
  weight: number;
  is_hard: boolean;
  enabled: boolean;
  priority: number;
  explanation: string;
  case_sensitive: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface RuleTestResult {
  rule_id: string;
  job_id: string;
  job_title: string;
  passed: boolean;
  detail: string;
  is_hard: boolean;
  awarded: number;
  would_reject: boolean;
}

export interface SavedSearch {
  id: string;
  name: string;
  keywords: string[];
  locations: string[];
  remote_only: boolean;
  min_salary_lpa: number | null;
  employment_types: string[];
  source_ids: string[];
  enabled: boolean;
  schedule_cron: string;
  last_run_at: string | null;
}

/* ------------------------------------------------------------------ sources */

export interface AdapterConfigField {
  key: string;
  label?: string;
  type?: string;
  required?: boolean;
  default?: JsonValue;
  placeholder?: string;
  help?: string;
  description?: string;
  options?: Array<string | { value: string; label?: string }>;
}

export interface SourceAdapterInfo {
  adapter_type: string;
  display_name: string;
  requires_credential: boolean;
  config_schema: AdapterConfigField[];
}

export interface JobSource {
  id: string;
  name: string;
  adapter_type: string;
  base_url: string;
  config: Record<string, JsonValue>;
  has_credential: boolean;
  enabled: boolean;
  priority: number;
  schedule_cron: string;
  query_templates: string[];
  rate_limit_per_hour: number;
  source_rules: Record<string, JsonValue>;
  health: SourceHealth;
  last_success_at: string | null;
  last_attempt_at: string | null;
  last_error: string;
  consecutive_failures: number;
  created_at?: string;
}

export interface TestResult {
  ok: boolean;
  message: string;
  details?: Record<string, JsonValue>;
}

/* --------------------------------------------------------------------- jobs */

export interface JobSkill {
  id?: string;
  skill_slug: string;
  skill_name: string;
  is_required: boolean;
  source: string;
  confidence: number;
}

export interface RuleResultEntry {
  rule_id?: string;
  name?: string;
  matched?: boolean;
  is_hard?: boolean;
  weight_applied?: number;
  explanation?: string;
}

export interface JobMatch {
  id?: string;
  job_id?: string;
  score: number;
  decision: MatchDecision;
  deterministic_score: number;
  semantic_score: number | null;
  breakdown: Record<string, number>;
  hard_fail_reasons: string[];
  matched_skills: string[];
  missing_skills: string[];
  positive_signals: string[];
  rule_results?: RuleResultEntry[];
  explanation: string;
  recommended_resume_id: string | null;
  recommendation_reason: string;
  engine_version?: string;
  is_current?: boolean;
  created_at?: string;
}

export interface JobEvent {
  id: string;
  job_id?: string;
  event_type: string;
  message: string;
  payload: Record<string, JsonValue>;
  actor: string;
  created_at: string;
}

export interface Job {
  id: string;
  source_id: string | null;
  source_name: string;
  external_id?: string;
  title: string;
  company: string;
  location: string;
  is_remote: boolean;
  url: string;
  apply_url?: string;
  /** Set when the posting published an address to apply to. */
  application_email?: string;
  description?: string;
  salary_min_lpa: number | null;
  salary_max_lpa: number | null;
  salary_raw?: string;
  currency?: string;
  employment_type: string;
  industry: string;
  experience_min_years?: number | null;
  experience_max_years?: number | null;
  posted_at: string | null;
  status: JobStatus;
  seen_count?: number;
  duplicate_sources?: string[];
  created_at: string;
  updated_at?: string;
  match: JobMatch | null;
  skills?: JobSkill[];
  events?: JobEvent[];
}

export interface JobCreateInput {
  title: string;
  company: string;
  location: string;
  is_remote: boolean;
  url: string;
  apply_url: string;
  description: string;
  salary_min_lpa: number | null;
  salary_max_lpa: number | null;
  employment_type: string;
  industry: string;
  experience_min_years: number | null;
  experience_max_years: number | null;
  posted_at: string | null;
  source_name: string;
}

export interface DiscoverResult {
  created: number;
  updated: number;
  skipped: number;
  errors: Array<Record<string, JsonValue>>;
  per_source: Record<string, JsonValue>;
}

export interface AiReview {
  verdict?: string;
  ai_score?: number | null;
  local_score?: number | null;
  reasons?: string[];
  gaps?: string[];
  pitch?: string;
  model?: string;
}

export interface CoverLetterResult {
  cover_letter: string;
  model?: string;
  evidence_ids?: string[];
}

export interface ResumeAdviceResult {
  recommended_resume_id?: string | null;
  recommended_resume?: string;
  headline?: string;
  emphasize?: string[];
  downplay?: string[];
  reason?: string;
}

export interface MatchPreviewResult {
  score: number;
  decision: MatchDecision;
  breakdown: Record<string, number>;
  hard_fail_reasons: string[];
  matched_skills: string[];
  missing_skills: string[];
  explanation: string;
}

/* ------------------------------------------------------------------ resumes */

export interface ResumeVersion {
  id: string;
  resume_id: string;
  version_number: number;
  label: string;
  origin: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  checksum_sha256?: string;
  extracted_text?: string;
  sections?: Record<string, JsonValue>;
  extracted_skills?: string[];
  parse_status: string;
  parse_error: string;
  tailored_for_job_id: string | null;
  generation_notes?: Record<string, JsonValue>;
  created_at: string;
}

export interface Resume {
  id: string;
  name: string;
  description: string;
  tags: string[];
  role_focus: string[];
  industry_focus: string[];
  skill_focus: string[];
  is_active: boolean;
  is_default: boolean;
  current_version_id: string | null;
  versions?: ResumeVersion[];
  version_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface TailorEvidence {
  evidence_id: string;
  kind: string;
  content: string;
  score: number;
  source: string;
}

export interface TailorValidation {
  ok: boolean;
  unsupported_tokens: string[];
  note: string;
}

export interface TailorResult {
  job_id: string;
  resume_id: string;
  summary: string;
  highlights: string[];
  skills_order: string[];
  changed_sections: Array<{ section: string; change: string; rationale?: string }>;
  omitted: string[];
  unsupported_requests: string[];
  evidence: TailorEvidence[];
  validation: TailorValidation;
  saved_version_id: string | null;
  original_text: string;
}

/* -------------------------------------------------------------- answer bank */

export interface AnswerBankEntry {
  id: string;
  question: string;
  normalized_key: string;
  answer: string;
  category: string;
  variables: Record<string, JsonValue>;
  source: string;
  state: AnswerState;
  confidence: number;
  enabled: boolean;
  job_id: string | null;
  company_normalized: string;
  priority: number;
  created_at?: string;
  updated_at?: string;
}

export interface ResolvedAnswer {
  question: string;
  answer: string;
  state: AnswerState;
  confidence: number;
  resolved_from: string;
  answer_bank_id?: string | null;
  evidence_ids?: string[];
}

/* ------------------------------------------------------------- applications */

export interface ApplicationStatusHistoryEntry {
  id: string;
  from_status: string;
  to_status: string;
  reason: string;
  actor: string;
  created_at: string;
}

export interface ApplicationAnswer {
  id: string;
  question: string;
  answer: string;
  state: AnswerState;
  confidence: number;
  resolved_from: string;
  answer_bank_id: string | null;
  evidence_ids: string[];
}

export interface ApplicationAsset {
  id: string;
  asset_type: string;
  content: string;
  storage_path: string;
  version: number;
  is_current: boolean;
  generated_by: string;
  model_used: string;
  evidence_ids: string[];
  validation: Record<string, JsonValue>;
  created_at: string;
}

export interface FollowUp {
  id: string;
  application_id: string;
  due_date: string;
  kind: string;
  note: string;
  completed_at: string | null;
  notified_at: string | null;
  created_at?: string;
  job_title?: string;
  company?: string;
}

export interface Recruiter {
  id: string;
  name: string;
  email: string;
  phone: string;
  company: string;
  linkedin_url: string;
  notes: string;
}

export interface Interview {
  id: string;
  round_name: string;
  scheduled_at: string | null;
  mode: string;
  interviewers: string[];
  outcome: string;
  feedback: string;
  notes: string;
}

export interface PrepareResult {
  application_id: string;
  assets_generated: string[];
  answers_resolved: number;
  answers_needing_review: number;
  warnings: string[];
}

export interface Application {
  id: string;
  job_id: string;
  resume_version_id: string | null;
  status: ApplicationStatus;
  channel: string;
  match_score: number | null;
  approved_at: string | null;
  approved_by: string;
  submitted_at: string | null;
  closed_at: string | null;
  next_action: string;
  next_action_due: string | null;
  notes: string;
  failure_reason: string;
  outcome_reason: string;
  recruiter_id: string | null;
  created_at: string;
  updated_at?: string;
  job?: Job;
  job_title?: string;
  company?: string;
  history?: ApplicationStatusHistoryEntry[];
  answers?: ApplicationAnswer[];
  assets?: ApplicationAsset[];
  followups?: FollowUp[];
  interviews?: Interview[];
  recruiter?: Recruiter | null;
}

/* ------------------------------------------------------------ notifications */

export interface NotificationChannel {
  id: string;
  channel_type: NotificationChannelType;
  display_name: string;
  enabled: boolean;
  config: Record<string, JsonValue>;
  has_credential: boolean;
  requires_credential: boolean;
  config_schema: AdapterConfigField[];
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_error: string;
}

export interface NotificationPreferences {
  event_routing: Record<string, string[]>;
  quiet_hours_start: string;
  quiet_hours_end: string;
  timezone: string;
  daily_digest_enabled: boolean;
  daily_digest_time: string;
  weekly_summary_enabled: boolean;
  instant_alerts_enabled: boolean;
  failures_only: boolean;
}

export interface NotificationEvent {
  id: string;
  event_type: string;
  channel_type: string;
  subject: string;
  body: string;
  status: NotificationStatus;
  error: string;
  sent_at: string | null;
  attempts: number;
  created_at: string;
}

/* ------------------------------------------------------------- integrations */

export interface Integration {
  key: string;
  label: string;
  provider: string;
  connected: boolean;
  /** Masked value only — the plaintext secret never reaches the browser. */
  masked_value: string;
  source: "database" | "environment" | "none";
  last_tested_at: string | null;
  last_test_ok: boolean | null;
  last_test_error: string;
  rotated_at: string | null;
}

/* --------------------------------------------------------------- automation */

export interface Agent {
  id: string;
  key: string;
  name: string;
  description: string;
  enabled: boolean;
  schedule_cron: string;
  config: Record<string, JsonValue>;
  max_retries: number;
  last_run_at: string | null;
  last_status: string;
  next_run_at: string | null;
}

export interface AgentRunStep {
  id: string;
  sequence: number;
  name: string;
  status: string;
  message: string;
  payload: Record<string, JsonValue>;
  duration_ms: number | null;
}

export interface AgentRun {
  id: string;
  agent_id: string | null;
  agent_key: string;
  trigger: string;
  status: AgentRunStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  items_processed: number;
  items_succeeded: number;
  items_failed: number;
  retry_count: number;
  summary: Record<string, JsonValue>;
  error: string;
  created_at: string;
  steps?: AgentRunStep[];
}

export interface Schedule {
  id: string;
  key: string;
  description: string;
  cron: string;
  timezone: string;
  enabled: boolean;
  agent_key: string;
  payload: Record<string, JsonValue>;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string;
}

/* ------------------------------------------ dashboard, analytics, audit, ai */

export interface DashboardCounts {
  [key: string]: number;
}

export interface Dashboard {
  counts: DashboardCounts;
  daily_run: {
    last_run_at: string | null;
    status: string;
    next_run_at: string | null;
    scheduler_enabled: boolean;
  };
  integration_health: Array<{
    id: string;
    name: string;
    adapter_type: string;
    health: string;
    enabled: boolean;
    last_success_at: string | null;
    last_error?: string;
  }>;
  ai_usage: {
    requests_today: number;
    tokens_today: number;
    estimated_cost_today_usd: number;
    estimated_cost_month_usd: number;
    budget_usd: number;
    budget_exhausted: boolean;
  };
  recent_activity: Array<{
    created_at: string;
    action: string;
    summary: string;
    entity_type?: string;
    entity_id?: string;
    success?: boolean;
  }>;
  application_cap: { used_today: number; cap: number; remaining: number };
  top_jobs: Array<{ id: string; title: string; company: string; score: number; decision: string }>;
}

export interface Analytics {
  days: number;
  jobs_discovered: number;
  jobs_qualified: number;
  average_match_score: number;
  applications_submitted: number;
  applications_per_week: Array<{ week: string; count: number }>;
  interview_rate: number;
  response_rate: number;
  top_skills_requested: Array<{ skill: string; count: number }>;
  source_conversion: Array<{ source: string; jobs: number; qualified: number; rate: number }>;
  rejection_reasons: Array<{ reason: string; count: number }>;
  resume_performance: Array<{ resume: string; applications: number }>;
  average_days_to_response: number | null;
}

export interface AiStatus {
  enabled: boolean;
  model: string | null;
  embedding_model: string | null;
  budget_usd: number;
  spent_this_month_usd: number;
  remaining_usd: number | null;
  exhausted: boolean;
}

export interface AiUsage {
  days: number;
  requests: number;
  total_tokens: number;
  estimated_cost_usd: number;
  avg_latency_ms: number;
  cache_hits: number;
  budget_usd: number;
  spent_this_month_usd: number;
  remaining_usd: number | null;
  exhausted: boolean;
  by_function: Array<{ function: string; requests: number; tokens: number; estimated_cost_usd: number }>;
}

export interface AuditLog {
  id: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  summary: string;
  before: JsonObject | null;
  after: JsonObject | null;
  ip_address: string;
  user_agent: string;
  success: boolean;
  created_at: string;
}

export interface SystemSetting {
  key: string;
  value: JsonValue;
  description: string;
}
