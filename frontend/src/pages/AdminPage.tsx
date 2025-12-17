import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  Cog6ToothIcon,
  ArrowPathIcon,
  DocumentTextIcon,
  ServerIcon,
  ClipboardDocumentListIcon,
} from '@heroicons/react/24/outline'
import { formatDistanceToNow } from 'date-fns'
import toast from 'react-hot-toast'
import { adminApi } from '../api/client'
import { useAuthStore } from '../stores/auth'

type Tab = 'status' | 'config' | 'audit'

export default function AdminPage() {
  const user = useAuthStore((state) => state.user)
  const [activeTab, setActiveTab] = useState<Tab>('status')
  const [configType, setConfigType] = useState<'parsers' | 'correlation' | 'maintenance'>('parsers')

  const { data: ingestionStatus, refetch: refetchStatus } = useQuery({
    queryKey: ['admin', 'ingestion'],
    queryFn: adminApi.getIngestionStatus,
    refetchInterval: 30000,
  })

  const { data: config } = useQuery({
    queryKey: ['admin', 'config', configType],
    queryFn: () => adminApi.getConfig(configType),
    enabled: activeTab === 'config',
  })

  const { data: auditLog } = useQuery({
    queryKey: ['admin', 'audit'],
    queryFn: () => adminApi.getAuditLog({ limit: 50 }),
    enabled: activeTab === 'audit',
  })

  const { data: severityStats } = useQuery({
    queryKey: ['admin', 'severity'],
    queryFn: adminApi.getSeverityBreakdown,
  })

  const { data: sourceStats } = useQuery({
    queryKey: ['admin', 'sources'],
    queryFn: adminApi.getSourceBreakdown,
  })

  const reloadMutation = useMutation({
    mutationFn: adminApi.reloadConfig,
    onSuccess: () => toast.success('Config reload requested'),
    onError: () => toast.error('Failed to reload config'),
  })

  const isAdmin = user?.role === 'admin'

  const tabs = [
    { id: 'status' as Tab, name: 'Ingestion Status', icon: ServerIcon },
    { id: 'config' as Tab, name: 'Configuration', icon: Cog6ToothIcon },
    { id: 'audit' as Tab, name: 'Audit Log', icon: ClipboardDocumentListIcon },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Admin</h1>
        <p className="mt-1 text-sm text-gray-500">System configuration and monitoring</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm ${
                activeTab === tab.id
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              <tab.icon className="h-5 w-5" />
              {tab.name}
            </button>
          ))}
        </nav>
      </div>

      {/* Ingestion Status Tab */}
      {activeTab === 'status' && (
        <div className="space-y-6">
          <div className="flex justify-end">
            <button onClick={() => refetchStatus()} className="btn-secondary">
              <ArrowPathIcon className="h-5 w-5 mr-1" />
              Refresh
            </button>
          </div>

          {/* Folder Status */}
          <div className="card overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-medium text-gray-900">IMAP Folder Status</h2>
            </div>
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Folder</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last UID</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Processed</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Poll</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {ingestionStatus?.folders?.map((folder: any) => (
                  <tr key={folder.folder}>
                    <td className="px-6 py-4 whitespace-nowrap font-medium text-gray-900">{folder.folder}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-500">{folder.last_uid}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-500">{folder.emails_processed}</td>
                    <td className="px-6 py-4 whitespace-nowrap text-gray-500">
                      {folder.last_poll_at
                        ? formatDistanceToNow(new Date(folder.last_poll_at), { addSuffix: true })
                        : 'Never'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {folder.error_count > 0 ? (
                        <span className="badge bg-red-100 text-red-800" title={folder.last_error}>
                          Error ({folder.error_count})
                        </span>
                      ) : (
                        <span className="badge bg-green-100 text-green-800">OK</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* By Severity */}
            <div className="card p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Incidents by Severity</h3>
              <div className="space-y-2">
                {severityStats?.breakdown?.map((item: any) => (
                  <div key={`${item.severity}-${item.status}`} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`badge badge-${item.severity}`}>{item.severity}</span>
                      <span className="text-sm text-gray-500">{item.status}</span>
                    </div>
                    <span className="font-medium">{item.count}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* By Source */}
            <div className="card p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Incidents by Source</h3>
              <div className="space-y-2">
                {sourceStats?.sources?.map((source: any) => (
                  <div key={source.source_tool} className="flex items-center justify-between">
                    <span className="text-sm text-gray-900">{source.source_tool}</span>
                    <div className="flex items-center gap-4">
                      <span className="text-sm text-gray-500">{source.total} total</span>
                      <span className="text-sm text-red-600">{source.open} open</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Config Tab */}
      {activeTab === 'config' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              {(['parsers', 'correlation', 'maintenance'] as const).map((type) => (
                <button
                  key={type}
                  onClick={() => setConfigType(type)}
                  className={`px-4 py-2 rounded-md text-sm font-medium ${
                    configType === type
                      ? 'bg-primary-100 text-primary-700'
                      : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                  }`}
                >
                  {type.charAt(0).toUpperCase() + type.slice(1)}
                </button>
              ))}
            </div>
            {isAdmin && (
              <button onClick={() => reloadMutation.mutate()} className="btn-primary">
                <ArrowPathIcon className="h-5 w-5 mr-1" />
                Reload Config
              </button>
            )}
          </div>

          <div className="card">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center gap-2">
              <DocumentTextIcon className="h-5 w-5 text-gray-400" />
              <h2 className="text-lg font-medium text-gray-900">{configType}.yml</h2>
              {config?.source && (
                <span className="badge bg-gray-100 text-gray-600">{config.source}</span>
              )}
            </div>
            <div className="p-6">
              <pre className="text-sm text-gray-800 bg-gray-50 p-4 rounded-lg overflow-x-auto max-h-96">
                {config?.config ? JSON.stringify(config.config, null, 2) : 'No configuration loaded'}
              </pre>
            </div>
          </div>
        </div>
      )}

      {/* Audit Log Tab */}
      {activeTab === 'audit' && (
        <div className="card overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Recent Activity</h2>
          </div>
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Time</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">User</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Action</th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Entity</th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {auditLog?.entries?.map((entry: any) => (
                <tr key={entry.id}>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {formatDistanceToNow(new Date(entry.created_at), { addSuffix: true })}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {entry.username || 'System'}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <span className="badge bg-gray-100 text-gray-800">{entry.action}</span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {entry.entity_type}
                    {entry.entity_id && (
                      <span className="ml-1 font-mono text-xs">({entry.entity_id.substring(0, 8)}...)</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
