import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Dialog } from '@headlessui/react'
import { ArrowPathIcon, EnvelopeIcon } from '@heroicons/react/24/outline'
import { formatDistanceToNow, format } from 'date-fns'
import toast from 'react-hot-toast'
import { quarantineApi } from '../api/client'
import { RawEmail } from '../types'
import { useAuthStore } from '../stores/auth'

export default function QuarantinePage() {
  const queryClient = useQueryClient()
  const user = useAuthStore((state) => state.user)
  const [selectedEmail, setSelectedEmail] = useState<RawEmail | null>(null)
  const [page, setPage] = useState(1)

  const { data, isLoading } = useQuery({
    queryKey: ['quarantine', page],
    queryFn: () => quarantineApi.list({ page, page_size: 25 }),
  })

  const { data: stats } = useQuery({
    queryKey: ['quarantine', 'stats'],
    queryFn: quarantineApi.stats,
  })

  const retryMutation = useMutation({
    mutationFn: (id: string) => quarantineApi.retry(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quarantine'] })
      toast.success('Email queued for retry')
    },
    onError: () => toast.error('Failed to retry'),
  })

  const canManage = user?.role === 'operator' || user?.role === 'admin'

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Quarantine</h1>
          <p className="mt-1 text-sm text-gray-500">
            {stats?.total || 0} emails failed to parse
          </p>
        </div>
      </div>

      {/* Stats by folder */}
      {stats?.by_folder && stats.by_folder.length > 0 && (
        <div className="card p-4">
          <h2 className="text-sm font-medium text-gray-700 mb-3">By Folder</h2>
          <div className="flex flex-wrap gap-3">
            {stats.by_folder.map((folder: any) => (
              <div key={folder.folder} className="bg-gray-50 rounded-lg px-4 py-2">
                <span className="font-medium text-gray-900">{folder.folder}</span>
                <span className="ml-2 text-gray-500">{folder.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Email List */}
      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Email
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Folder
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Error
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Received
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {isLoading ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-gray-500">
                  Loading...
                </td>
              </tr>
            ) : data?.items?.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-gray-500">
                  No quarantined emails
                </td>
              </tr>
            ) : (
              data?.items?.map((email: RawEmail & { parse_status: string; parse_error?: string }) => (
                <tr key={email.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div
                      className="cursor-pointer"
                      onClick={() => setSelectedEmail(email)}
                    >
                      <div className="text-sm font-medium text-gray-900 truncate max-w-xs">
                        {email.subject || '(no subject)'}
                      </div>
                      <div className="text-sm text-gray-500">{email.from_address}</div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className="badge bg-gray-100 text-gray-800">{email.folder}</span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="text-sm text-red-600 truncate max-w-xs" title={email.parse_error}>
                      {email.parse_error || 'Unknown error'}
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {formatDistanceToNow(new Date(email.received_at), { addSuffix: true })}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right">
                    {canManage && (
                      <button
                        onClick={() => retryMutation.mutate(email.id)}
                        className="text-primary-600 hover:text-primary-700 text-sm"
                      >
                        <ArrowPathIcon className="h-5 w-5 inline mr-1" />
                        Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200">
            <div className="text-sm text-gray-700">
              Page {page} of {data.total_pages}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="btn-secondary"
              >
                Previous
              </button>
              <button
                onClick={() => setPage((p) => Math.min(data.total_pages, p + 1))}
                disabled={page === data.total_pages}
                className="btn-secondary"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Email Detail Dialog */}
      <Dialog open={!!selectedEmail} onClose={() => setSelectedEmail(null)} className="relative z-50">
        <div className="fixed inset-0 bg-black/30" aria-hidden="true" />
        <div className="fixed inset-0 flex items-center justify-center p-4">
          <Dialog.Panel className="mx-auto max-w-3xl w-full bg-white rounded-lg shadow-xl max-h-[80vh] overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <Dialog.Title className="text-lg font-medium flex items-center gap-2">
                <EnvelopeIcon className="h-5 w-5 text-gray-400" />
                Quarantined Email
              </Dialog.Title>
              <button onClick={() => setSelectedEmail(null)} className="text-gray-400 hover:text-gray-500">
                &times;
              </button>
            </div>
            {selectedEmail && (
              <div className="p-6 overflow-y-auto max-h-[60vh]">
                <div className="space-y-4">
                  <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                    <h4 className="text-sm font-medium text-red-800">Parse Error</h4>
                    <p className="text-sm text-red-700 mt-1">{(selectedEmail as any).parse_error || 'Unknown error'}</p>
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <span className="text-sm font-medium text-gray-500">Subject</span>
                      <p className="text-sm text-gray-900">{selectedEmail.subject || '(no subject)'}</p>
                    </div>
                    <div>
                      <span className="text-sm font-medium text-gray-500">From</span>
                      <p className="text-sm text-gray-900">{selectedEmail.from_address}</p>
                    </div>
                    <div>
                      <span className="text-sm font-medium text-gray-500">Folder</span>
                      <p className="text-sm text-gray-900">{selectedEmail.folder}</p>
                    </div>
                    <div>
                      <span className="text-sm font-medium text-gray-500">Date</span>
                      <p className="text-sm text-gray-900">
                        {selectedEmail.date_header && format(new Date(selectedEmail.date_header), 'PPpp')}
                      </p>
                    </div>
                  </div>

                  <div>
                    <span className="text-sm font-medium text-gray-500">Body</span>
                    <pre className="mt-2 text-sm text-gray-900 whitespace-pre-wrap bg-gray-50 p-4 rounded-lg overflow-x-auto max-h-64">
                      {selectedEmail.body_text || selectedEmail.body_html || 'No body content'}
                    </pre>
                  </div>
                </div>

                {canManage && (
                  <div className="flex justify-end gap-2 mt-6">
                    <button
                      onClick={() => {
                        retryMutation.mutate(selectedEmail.id)
                        setSelectedEmail(null)
                      }}
                      className="btn-primary"
                    >
                      <ArrowPathIcon className="h-5 w-5 mr-1" />
                      Retry Parsing
                    </button>
                  </div>
                )}
              </div>
            )}
          </Dialog.Panel>
        </div>
      </Dialog>
    </div>
  )
}
