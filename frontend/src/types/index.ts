export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info'
export type IncidentStatus = 'open' | 'acknowledged' | 'resolved' | 'suppressed'
export type AlertState = 'firing' | 'resolved' | 'unknown'
export type SuppressMode = 'mute' | 'downgrade' | 'digest'
export type MaintenanceSource = 'email' | 'manual' | 'graph'

export interface Incident {
  id: string
  fingerprint: string
  title: string
  description?: string
  source_tool?: string
  environment?: string
  region?: string
  host?: string
  check_name?: string
  service?: string
  severity: Severity
  status: IncidentStatus
  first_seen_at: string
  last_seen_at: string
  resolved_at?: string
  acknowledged_at?: string
  event_count: number
  is_in_maintenance: boolean
  tags: string[]
  labels: Record<string, string>
  ai_summary?: string
  ai_category?: string
  ai_owner_team?: string
  ai_recommended_checks?: string[]
  ai_suggested_runbooks?: Array<{ id: string; title: string; url?: string }>
  ai_safe_actions?: string[]
  ai_confidence?: number
  ai_evidence?: Array<{ source: string; snippet: string }>
  ai_enriched_at?: string
}

export interface AlertEvent {
  id: string
  raw_email_id?: string
  source_tool: string
  environment?: string
  region?: string
  host?: string
  check_name?: string
  service?: string
  severity: Severity
  state: AlertState
  occurred_at: string
  normalized_signature: string
  fingerprint: string
  payload: Record<string, any>
  tags: string[]
  is_suppressed: boolean
  suppression_reason?: string
  created_at: string
}

export interface IncidentComment {
  id: string
  incident_id: string
  user_id?: string
  content: string
  is_system_generated: boolean
  created_at: string
  updated_at: string
}

export interface MaintenanceWindow {
  id: string
  source: MaintenanceSource
  external_event_id?: string
  title: string
  description?: string
  organizer?: string
  organizer_email?: string
  start_ts: string
  end_ts: string
  timezone: string
  is_recurring: boolean
  scope: MaintenanceScope
  suppress_mode: SuppressMode
  reason?: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface MaintenanceScope {
  hosts?: string[]
  host_regex?: string
  services?: string[]
  service_regex?: string
  tags?: string[]
  environments?: string[]
  regions?: string[]
}

export interface RawEmail {
  id: string
  folder: string
  uid: number
  message_id?: string
  subject?: string
  from_address?: string
  to_addresses: string[]
  date_header?: string
  headers: Record<string, string>
  body_text?: string
  body_html?: string
  attachments: Array<{ filename: string; content_type: string; size: number }>
  received_at: string
  parse_status?: string
  parse_error?: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}
