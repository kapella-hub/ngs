import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Dialog } from '@headlessui/react'
import { PlusIcon, CalendarIcon, TrashIcon } from '@heroicons/react/24/outline'
import { format, formatDistanceToNow } from 'date-fns'
import toast from 'react-hot-toast'
import { maintenanceApi } from '../api/client'
import { MaintenanceWindow, SuppressMode } from '../types'
import { useAuthStore } from '../stores/auth'

export default function MaintenancePage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.user)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [selectedWindow, setSelectedWindow] = useState<MaintenanceWindow | null>(null)

  // Form state
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [startTs, setStartTs] = useState('')
  const [endTs, setEndTs] = useState('')
  const [suppressMode, setSuppressMode] = useState<SuppressMode>('mute')
  const [reason, setReason] = useState('')
  const [hostPattern, setHostPattern] = useState('')
  const [servicePattern, setServicePattern] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['maintenance'],
    queryFn: () => maintenanceApi.list({ include_past: false }),
    refetchInterval: 60000,
  })

  const { data: activeWindows } = useQuery({
    queryKey: ['maintenance', 'active'],
    queryFn: maintenanceApi.getActive,
    refetchInterval: 30000,
  })

  const createMutation = useMutation({
    mutationFn: () =>
      maintenanceApi.create({
        title,
        description,
        start_ts: new Date(startTs).toISOString(),
        end_ts: new Date(endTs).toISOString(),
        suppress_mode: suppressMode,
        reason,
        scope: {
          hosts: hostPattern ? hostPattern.split(',').map((h) => h.trim()) : [],
          services: servicePattern ? servicePattern.split(',').map((s) => s.trim()) : [],
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['maintenance'] })
      toast.success('Maintenance window created')
      setShowCreateDialog(false)
      resetForm()
    },
    onError: () => toast.error('Failed to create maintenance window'),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => maintenanceApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['maintenance'] })
      toast.success('Maintenance window deleted')
      setSelectedWindow(null)
    },
    onError: () => toast.error('Failed to delete maintenance window'),
  })

  const resetForm = () => {
    setTitle('')
    setDescription('')
    setStartTs('')
    setEndTs('')
    setSuppressMode('mute')
    setReason('')
    setHostPattern('')
    setServicePattern('')
  }

  const canManage = user?.role === 'operator' || user?.role === 'admin'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Maintenance Windows</h1>
          <p className="mt-1 text-sm text-gray-500">
            {activeWindows?.length || 0} currently active
          </p>
        </div>
        {canManage && (
          <button onClick={() => setShowCreateDialog(true)} className="btn-primary">
            <PlusIcon className="h-5 w-5 mr-1" />
            Create Window
          </button>
        )}
      </div>

      {/* Active Maintenance */}
      {activeWindows && activeWindows.length > 0 && (
        <div className="card p-6 bg-blue-50 border-blue-200">
          <h2 className="text-lg font-medium text-blue-900 mb-4">Active Now</h2>
          <div className="space-y-3">
            {activeWindows.map((window: MaintenanceWindow) => (
              <div key={window.id} className="flex items-center justify-between bg-white p-3 rounded-lg">
                <div>
                  <p className="font-medium text-gray-900">{window.title}</p>
                  <p className="text-sm text-gray-500">
                    Ends {formatDistanceToNow(new Date(window.end_ts), { addSuffix: true })}
                  </p>
                </div>
                <span className="badge bg-blue-100 text-blue-800">{window.suppress_mode}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Maintenance List */}
      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Window
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Source
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Time
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Mode
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {isLoading ? (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                  Loading...
                </td>
              </tr>
            ) : data?.items?.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-6 py-12 text-center text-gray-500">
                  No maintenance windows found
                </td>
              </tr>
            ) : (
              data?.items?.map((window: MaintenanceWindow) => {
                const now = new Date()
                const start = new Date(window.start_ts)
                const end = new Date(window.end_ts)
                const isActive = now >= start && now <= end
                const isPast = now > end
                const isFuture = now < start

                return (
                  <tr key={window.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="text-sm font-medium text-gray-900">{window.title}</div>
                      {window.organizer && (
                        <div className="text-sm text-gray-500">{window.organizer}</div>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`badge ${window.source === 'email' ? 'bg-purple-100 text-purple-800' : 'bg-gray-100 text-gray-800'}`}>
                        {window.source}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      <div>{format(start, 'MMM d, HH:mm')}</div>
                      <div className="text-xs">to {format(end, 'MMM d, HH:mm')}</div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="badge bg-blue-100 text-blue-800">{window.suppress_mode}</span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {isActive && <span className="badge bg-green-100 text-green-800">Active</span>}
                      {isFuture && <span className="badge bg-yellow-100 text-yellow-800">Scheduled</span>}
                      {isPast && <span className="badge bg-gray-100 text-gray-800">Ended</span>}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right">
                      <button
                        onClick={() => setSelectedWindow(window)}
                        className="text-primary-600 hover:text-primary-700 text-sm"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onClose={() => setShowCreateDialog(false)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-lg w-full bg-white rounded-lg shadow-xl p-6 max-h-[90vh] overflow-y-auto">
            <Dialog.Title className="text-lg font-medium mb-4">Create Maintenance Window</Dialog.Title>
            <form
              onSubmit={(e) => {
                e.preventDefault()
                createMutation.mutate()
              }}
              className="space-y-4"
            >
              <div>
                <label className="label">Title</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="input"
                  required
                />
              </div>
              <div>
                <label className="label">Description</label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="input h-20"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="label">Start Time</label>
                  <input
                    type="datetime-local"
                    value={startTs}
                    onChange={(e) => setStartTs(e.target.value)}
                    className="input"
                    required
                  />
                </div>
                <div>
                  <label className="label">End Time</label>
                  <input
                    type="datetime-local"
                    value={endTs}
                    onChange={(e) => setEndTs(e.target.value)}
                    className="input"
                    required
                  />
                </div>
              </div>
              <div>
                <label className="label">Suppress Mode</label>
                <select
                  value={suppressMode}
                  onChange={(e) => setSuppressMode(e.target.value as SuppressMode)}
                  className="input"
                >
                  <option value="mute">Mute - No notifications</option>
                  <option value="downgrade">Downgrade - Lower severity</option>
                  <option value="digest">Digest - Show in periodic digest only</option>
                </select>
              </div>
              <div>
                <label className="label">Reason</label>
                <input
                  type="text"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  className="input"
                  placeholder="e.g., Server patching"
                />
              </div>
              <div>
                <label className="label">Hosts (comma-separated, supports wildcards)</label>
                <input
                  type="text"
                  value={hostPattern}
                  onChange={(e) => setHostPattern(e.target.value)}
                  className="input"
                  placeholder="e.g., web-*, db-01"
                />
              </div>
              <div>
                <label className="label">Services (comma-separated)</label>
                <input
                  type="text"
                  value={servicePattern}
                  onChange={(e) => setServicePattern(e.target.value)}
                  className="input"
                  placeholder="e.g., http, dns"
                />
              </div>
              <div className="flex justify-end gap-2 pt-4">
                <button type="button" onClick={() => setShowCreateDialog(false)} className="btn-secondary">
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Create
                </button>
              </div>
            </form>
          </Dialog.Panel>
        </div>
      </Dialog>

      {/* Detail Dialog */}
      <Dialog open={!!selectedWindow} onClose={() => setSelectedWindow(null)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-lg w-full bg-white rounded-lg shadow-xl p-6">
            {selectedWindow && (
              <>
                <Dialog.Title className="text-lg font-medium mb-4">{selectedWindow.title}</Dialog.Title>
                <dl className="space-y-3">
                  <div>
                    <dt className="text-sm text-gray-500">Source</dt>
                    <dd className="text-sm font-medium text-gray-900 capitalize">{selectedWindow.source}</dd>
                  </div>
                  <div>
                    <dt className="text-sm text-gray-500">Time</dt>
                    <dd className="text-sm font-medium text-gray-900">
                      {format(new Date(selectedWindow.start_ts), 'PPpp')} -{' '}
                      {format(new Date(selectedWindow.end_ts), 'PPpp')}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-sm text-gray-500">Mode</dt>
                    <dd className="text-sm font-medium text-gray-900 capitalize">{selectedWindow.suppress_mode}</dd>
                  </div>
                  {selectedWindow.reason && (
                    <div>
                      <dt className="text-sm text-gray-500">Reason</dt>
                      <dd className="text-sm font-medium text-gray-900">{selectedWindow.reason}</dd>
                    </div>
                  )}
                  {selectedWindow.organizer && (
                    <div>
                      <dt className="text-sm text-gray-500">Organizer</dt>
                      <dd className="text-sm font-medium text-gray-900">{selectedWindow.organizer}</dd>
                    </div>
                  )}
                </dl>
                <div className="flex justify-between mt-6">
                  {user?.role === 'admin' && (
                    <button
                      onClick={() => deleteMutation.mutate(selectedWindow.id)}
                      className="btn-danger"
                    >
                      <TrashIcon className="h-5 w-5 mr-1" />
                      Delete
                    </button>
                  )}
                  <button onClick={() => setSelectedWindow(null)} className="btn-secondary ml-auto">
                    Close
                  </button>
                </div>
              </>
            )}
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  )
}
