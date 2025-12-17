import { useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Dialog } from '@headlessui/react'
import {
  ArrowLeftIcon,
  CheckIcon,
  HandRaisedIcon,
  NoSymbolIcon,
  ChatBubbleLeftIcon,
  SparklesIcon,
  EnvelopeIcon,
  ClockIcon,
  WrenchScrewdriverIcon,
} from '@heroicons/react/24/outline'
import { formatDistanceToNow, format } from 'date-fns'
import toast from 'react-hot-toast'
import { incidentsApi } from '../api/client'
import { AlertEvent, IncidentComment } from '../types'
import SeverityBadge from '../components/SeverityBadge'
import StatusBadge from '../components/StatusBadge'

export default function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const queryClient = useQueryClient()
  const [showAckDialog, setShowAckDialog] = useState(false)
  const [showResolveDialog, setShowResolveDialog] = useState(false)
  const [showSuppressDialog, setShowSuppressDialog] = useState(false)
  const [comment, setComment] = useState('')
  const [suppressReason, setSuppressReason] = useState('')
  const [suppressDuration, setSuppressDuration] = useState(60)
  const [newComment, setNewComment] = useState('')
  const [selectedEvent, setSelectedEvent] = useState<string | null>(null)

  const { data: incident, isLoading } = useQuery({
    queryKey: ['incident', id],
    queryFn: () => incidentsApi.get(id!),
    enabled: !!id,
    refetchInterval: 30000,
  })

  const { data: comments } = useQuery({
    queryKey: ['incident', id, 'comments'],
    queryFn: () => incidentsApi.getComments(id!),
    enabled: !!id,
  })

  const { data: maintenanceInfo } = useQuery({
    queryKey: ['incident', id, 'maintenance'],
    queryFn: () => incidentsApi.getMaintenance(id!),
    enabled: !!id,
  })

  const { data: rawEmail } = useQuery({
    queryKey: ['rawEmail', id, selectedEvent],
    queryFn: () => incidentsApi.getRawEmail(id!, selectedEvent!),
    enabled: !!selectedEvent,
  })

  const ackMutation = useMutation({
    mutationFn: () => incidentsApi.acknowledge(id!, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incident', id] })
      toast.success('Incident acknowledged')
      setShowAckDialog(false)
      setComment('')
    },
    onError: () => toast.error('Failed to acknowledge incident'),
  })

  const resolveMutation = useMutation({
    mutationFn: () => incidentsApi.resolve(id!, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incident', id] })
      toast.success('Incident resolved')
      setShowResolveDialog(false)
      setComment('')
    },
    onError: () => toast.error('Failed to resolve incident'),
  })

  const suppressMutation = useMutation({
    mutationFn: () => incidentsApi.suppress(id!, { duration_minutes: suppressDuration, reason: suppressReason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incident', id] })
      toast.success('Incident suppressed')
      setShowSuppressDialog(false)
      setSuppressReason('')
    },
    onError: () => toast.error('Failed to suppress incident'),
  })

  const addCommentMutation = useMutation({
    mutationFn: () => incidentsApi.addComment(id!, newComment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incident', id, 'comments'] })
      toast.success('Comment added')
      setNewComment('')
    },
    onError: () => toast.error('Failed to add comment'),
  })

  if (isLoading || !incident) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-500">Loading...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-4">
          <Link to="/incidents" className="mt-1 p-2 hover:bg-gray-100 rounded-lg">
            <ArrowLeftIcon className="h-5 w-5 text-gray-500" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{incident.title}</h1>
            <div className="flex items-center gap-3 mt-2">
              <SeverityBadge severity={incident.severity} size="md" />
              <StatusBadge status={incident.status} size="md" />
              {incident.is_in_maintenance && (
                <span className="badge bg-blue-100 text-blue-800 px-3 py-1">
                  <WrenchScrewdriverIcon className="h-4 w-4 mr-1 inline" />
                  In Maintenance
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="flex gap-2">
          {incident.status === 'open' && (
            <button onClick={() => setShowAckDialog(true)} className="btn-secondary">
              <HandRaisedIcon className="h-5 w-5 mr-1" />
              Acknowledge
            </button>
          )}
          {incident.status !== 'resolved' && (
            <button onClick={() => setShowResolveDialog(true)} className="btn-primary">
              <CheckIcon className="h-5 w-5 mr-1" />
              Resolve
            </button>
          )}
          {incident.status !== 'suppressed' && (
            <button onClick={() => setShowSuppressDialog(true)} className="btn-secondary">
              <NoSymbolIcon className="h-5 w-5 mr-1" />
              Suppress
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          {/* Details */}
          <div className="card p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">Details</h2>
            <dl className="grid grid-cols-2 gap-4">
              <div>
                <dt className="text-sm text-gray-500">Host</dt>
                <dd className="text-sm font-medium text-gray-900">{incident.host || '-'}</dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">Check/Service</dt>
                <dd className="text-sm font-medium text-gray-900">{incident.check_name || incident.service || '-'}</dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">Source</dt>
                <dd className="text-sm font-medium text-gray-900">{incident.source_tool || '-'}</dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">Environment</dt>
                <dd className="text-sm font-medium text-gray-900">{incident.environment || '-'}</dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">First Seen</dt>
                <dd className="text-sm font-medium text-gray-900">
                  {format(new Date(incident.first_seen_at), 'PPpp')}
                </dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">Last Seen</dt>
                <dd className="text-sm font-medium text-gray-900">
                  {formatDistanceToNow(new Date(incident.last_seen_at), { addSuffix: true })}
                </dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">Event Count</dt>
                <dd className="text-sm font-medium text-gray-900">{incident.event_count}</dd>
              </div>
              <div>
                <dt className="text-sm text-gray-500">Fingerprint</dt>
                <dd className="text-sm font-mono text-gray-500">{incident.fingerprint}</dd>
              </div>
            </dl>
          </div>

          {/* AI Enrichment */}
          {incident.ai_enriched_at && (
            <div className="card p-6">
              <div className="flex items-center gap-2 mb-4">
                <SparklesIcon className="h-5 w-5 text-purple-500" />
                <h2 className="text-lg font-medium text-gray-900">AI Analysis</h2>
                {incident.ai_confidence && (
                  <span className="text-sm text-gray-500">
                    ({Math.round(incident.ai_confidence * 100)}% confidence)
                  </span>
                )}
              </div>

              {incident.ai_summary && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Summary</h3>
                  <p className="text-sm text-gray-600 whitespace-pre-wrap">{incident.ai_summary}</p>
                </div>
              )}

              {incident.ai_category && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Category</h3>
                  <span className="badge bg-purple-100 text-purple-800">{incident.ai_category}</span>
                </div>
              )}

              {incident.ai_recommended_checks && incident.ai_recommended_checks.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Recommended Checks</h3>
                  <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
                    {incident.ai_recommended_checks.map((check, i) => (
                      <li key={i}>{check}</li>
                    ))}
                  </ul>
                </div>
              )}

              {incident.ai_suggested_runbooks && incident.ai_suggested_runbooks.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Suggested Runbooks</h3>
                  <ul className="space-y-1">
                    {incident.ai_suggested_runbooks.map((rb, i) => (
                      <li key={i}>
                        {rb.url ? (
                          <a href={rb.url} target="_blank" rel="noopener noreferrer" className="text-sm text-primary-600 hover:underline">
                            {rb.title}
                          </a>
                        ) : (
                          <span className="text-sm text-gray-600">{rb.title}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {incident.ai_safe_actions && incident.ai_safe_actions.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium text-gray-700 mb-2">Safe Actions (Not Executed)</h3>
                  <ul className="list-disc list-inside text-sm text-gray-600 space-y-1">
                    {incident.ai_safe_actions.map((action, i) => (
                      <li key={i}>{action}</li>
                    ))}
                  </ul>
                </div>
              )}

              <p className="text-xs text-gray-400 mt-4">
                Enriched {formatDistanceToNow(new Date(incident.ai_enriched_at), { addSuffix: true })}
              </p>
            </div>
          )}

          {/* Events Timeline */}
          <div className="card">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-medium text-gray-900">Events Timeline</h2>
            </div>
            <div className="divide-y divide-gray-200 max-h-96 overflow-y-auto">
              {incident.recent_events?.map((event: AlertEvent) => (
                <div
                  key={event.id}
                  className="px-6 py-4 hover:bg-gray-50 cursor-pointer"
                  onClick={() => setSelectedEvent(event.id)}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex items-start gap-3">
                      <div className={`mt-1 w-2 h-2 rounded-full ${event.state === 'firing' ? 'bg-red-500' : 'bg-green-500'}`} />
                      <div>
                        <p className="text-sm text-gray-900">{event.state.toUpperCase()}</p>
                        <p className="text-xs text-gray-500">
                          {format(new Date(event.occurred_at), 'PPpp')}
                        </p>
                      </div>
                    </div>
                    {event.raw_email_id && (
                      <EnvelopeIcon className="h-5 w-5 text-gray-400" />
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Maintenance Info */}
          {maintenanceInfo?.in_maintenance && maintenanceInfo.window && (
            <div className="card p-6 bg-blue-50 border-blue-200">
              <div className="flex items-center gap-2 mb-3">
                <WrenchScrewdriverIcon className="h-5 w-5 text-blue-600" />
                <h3 className="font-medium text-blue-900">Maintenance Window</h3>
              </div>
              <p className="text-sm text-blue-800 mb-2">{maintenanceInfo.window.title}</p>
              <p className="text-xs text-blue-600">
                {format(new Date(maintenanceInfo.window.start_ts), 'PPp')} -{' '}
                {format(new Date(maintenanceInfo.window.end_ts), 'PPp')}
              </p>
            </div>
          )}

          {/* Comments */}
          <div className="card">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="font-medium text-gray-900">Comments</h3>
            </div>
            <div className="p-4 space-y-4 max-h-64 overflow-y-auto">
              {comments?.length === 0 ? (
                <p className="text-sm text-gray-500 text-center">No comments yet</p>
              ) : (
                comments?.map((comment: IncidentComment) => (
                  <div key={comment.id} className={`text-sm ${comment.is_system_generated ? 'text-gray-500 italic' : ''}`}>
                    <p className="text-gray-900">{comment.content}</p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatDistanceToNow(new Date(comment.created_at), { addSuffix: true })}
                    </p>
                  </div>
                ))
              )}
            </div>
            <div className="px-4 py-3 border-t border-gray-200">
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  addCommentMutation.mutate()
                }}
                className="flex gap-2"
              >
                <input
                  type="text"
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  placeholder="Add comment..."
                  className="input text-sm flex-1"
                />
                <button type="submit" disabled={!newComment} className="btn-primary">
                  <ChatBubbleLeftIcon className="h-4 w-4" />
                </button>
              </form>
            </div>
          </div>
        </div>
      </div>

      {/* Raw Email Viewer */}
      <Dialog open={!!selectedEvent} onClose={() => setSelectedEvent(null)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-3xl w-full bg-white rounded-lg shadow-xl max-h-[80vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <Dialog.Title className="text-lg font-medium">Raw Email</Dialog.Title>
              <button onClick={() => setSelectedEvent(null)} className="text-gray-400 hover:text-gray-500">
                &times;
              </button>
            </div>
            <div className="p-6 overflow-y-auto max-h-[60vh]">
              {rawEmail ? (
                <div className="space-y-4">
                  <div>
                    <span className="text-sm font-medium text-gray-500">Subject:</span>
                    <p className="text-sm text-gray-900">{rawEmail.subject}</p>
                  </div>
                  <div>
                    <span className="text-sm font-medium text-gray-500">From:</span>
                    <p className="text-sm text-gray-900">{rawEmail.from_address}</p>
                  </div>
                  <div>
                    <span className="text-sm font-medium text-gray-500">Date:</span>
                    <p className="text-sm text-gray-900">
                      {rawEmail.date_header && format(new Date(rawEmail.date_header), 'PPpp')}
                    </p>
                  </div>
                  <div>
                    <span className="text-sm font-medium text-gray-500">Body:</span>
                    <pre className="mt-2 text-sm text-gray-900 whitespace-pre-wrap bg-gray-50 p-4 rounded-lg overflow-x-auto">
                      {rawEmail.body_text || rawEmail.body_html || 'No body content'}
                    </pre>
                  </div>
                </div>
              ) : (
                <p className="text-gray-500">Loading...</p>
              )}
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>

      {/* Acknowledge Dialog */}
      <Dialog open={showAckDialog} onClose={() => setShowAckDialog(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-md w-full bg-white rounded-lg shadow-xl p-6">
            <Dialog.Title className="text-lg font-medium mb-4">Acknowledge Incident</Dialog.Title>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Add a comment (optional)"
              className="input w-full h-24"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowAckDialog(false)} className="btn-secondary">Cancel</button>
              <button onClick={() => ackMutation.mutate()} className="btn-primary">Acknowledge</button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>

      {/* Resolve Dialog */}
      <Dialog open={showResolveDialog} onClose={() => setShowResolveDialog(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-md w-full bg-white rounded-lg shadow-xl p-6">
            <Dialog.Title className="text-lg font-medium mb-4">Resolve Incident</Dialog.Title>
            <textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Add a comment (optional)"
              className="input w-full h-24"
            />
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowResolveDialog(false)} className="btn-secondary">Cancel</button>
              <button onClick={() => resolveMutation.mutate()} className="btn-primary">Resolve</button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>

      {/* Suppress Dialog */}
      <Dialog open={showSuppressDialog} onClose={() => setShowSuppressDialog(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-md w-full bg-white rounded-lg shadow-xl p-6">
            <Dialog.Title className="text-lg font-medium mb-4">Suppress Incident</Dialog.Title>
            <div className="space-y-4">
              <div>
                <label className="label">Reason</label>
                <input
                  type="text"
                  value={suppressReason}
                  onChange={(e) => setSuppressReason(e.target.value)}
                  placeholder="Why are you suppressing this?"
                  className="input"
                  required
                />
              </div>
              <div>
                <label className="label">Duration (minutes)</label>
                <input
                  type="number"
                  value={suppressDuration}
                  onChange={(e) => setSuppressDuration(parseInt(e.target.value))}
                  className="input"
                  min={1}
                  max={43200}
                />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setShowSuppressDialog(false)} className="btn-secondary">Cancel</button>
              <button onClick={() => suppressMutation.mutate()} disabled={!suppressReason} className="btn-danger">
                Suppress
              </button>
            </div>
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  )
}
