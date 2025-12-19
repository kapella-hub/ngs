import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  MagnifyingGlassIcon,
  FunnelIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from '@heroicons/react/24/outline'
import { formatDistanceToNow } from 'date-fns'
import { incidentsApi } from '../api/client'
import { Incident, IncidentStatus, Severity } from '../types'
import SeverityBadge from '../components/SeverityBadge'
import StatusBadge from '../components/StatusBadge'

const severityOptions: Severity[] = ['critical', 'high', 'medium', 'low', 'info']
const statusOptions: IncidentStatus[] = ['open', 'acknowledged', 'resolved', 'suppressed']

export default function IncidentsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState(searchParams.get('search') || '')

  const page = parseInt(searchParams.get('page') || '1')
  const status = searchParams.getAll('status') as IncidentStatus[]
  const severity = searchParams.getAll('severity') as Severity[]
  const inMaintenance = searchParams.get('in_maintenance')

  // Auto-expand filters when URL has filter params
  const hasActiveFilters = status.length > 0 || severity.length > 0 || inMaintenance !== null
  const [showFilters, setShowFilters] = useState(hasActiveFilters)

  const { data, isLoading } = useQuery({
    queryKey: ['incidents', { page, status, severity, search, inMaintenance }],
    queryFn: () =>
      incidentsApi.list({
        page,
        page_size: 25,
        status: status.length > 0 ? status : undefined,
        severity: severity.length > 0 ? severity : undefined,
        search: search || undefined,
        in_maintenance: inMaintenance === 'true' ? true : inMaintenance === 'false' ? false : undefined,
      }),
    refetchInterval: 30000,
  })

  const updateFilters = (key: string, value: string | string[] | null) => {
    const newParams = new URLSearchParams(searchParams)
    newParams.delete(key)
    if (value) {
      if (Array.isArray(value)) {
        value.forEach((v) => newParams.append(key, v))
      } else {
        newParams.set(key, value)
      }
    }
    // Only reset page to 1 when changing filters, not when changing page itself
    if (key !== 'page') {
      newParams.set('page', '1')
    }
    setSearchParams(newParams)
  }

  const toggleFilter = (key: string, value: string) => {
    const current = searchParams.getAll(key)
    if (current.includes(value)) {
      updateFilters(key, current.filter((v) => v !== value))
    } else {
      updateFilters(key, [...current, value])
    }
  }

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    updateFilters('search', search || null)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Incidents</h1>
          <p className="mt-1 text-sm text-gray-500">
            {data?.total || 0} total incidents
          </p>
        </div>
      </div>

      {/* Search and Filters */}
      <div className="card p-4">
        <div className="flex flex-col sm:flex-row gap-4">
          <form onSubmit={handleSearch} className="flex-1">
            <div className="relative">
              <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search incidents..."
                className="input pl-10"
              />
            </div>
          </form>
          <button
            onClick={() => setShowFilters(!showFilters)}
            className={`btn-secondary ${showFilters ? 'bg-gray-100' : ''}`}
          >
            <FunnelIcon className="h-5 w-5 mr-2" />
            Filters
            {hasActiveFilters && (
              <span className="ml-2 inline-flex items-center justify-center px-2 py-0.5 rounded-full text-xs font-medium bg-primary-600 text-white">
                {status.length + severity.length + (inMaintenance ? 1 : 0)}
              </span>
            )}
          </button>
          {hasActiveFilters && (
            <button
              onClick={() => {
                const newParams = new URLSearchParams()
                if (search) newParams.set('search', search)
                setSearchParams(newParams)
              }}
              className="btn-secondary text-red-600 hover:text-red-700"
            >
              Clear Filters
            </button>
          )}
        </div>

        {showFilters && (
          <div className="mt-4 pt-4 border-t border-gray-200">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <label className="label">Status</label>
                <div className="flex flex-wrap gap-2">
                  {statusOptions.map((s) => (
                    <button
                      key={s}
                      onClick={() => toggleFilter('status', s)}
                      className={`badge cursor-pointer ${
                        status.includes(s)
                          ? 'bg-primary-100 text-primary-800 ring-1 ring-primary-600'
                          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="label">Severity</label>
                <div className="flex flex-wrap gap-2">
                  {severityOptions.map((s) => (
                    <button
                      key={s}
                      onClick={() => toggleFilter('severity', s)}
                      className={`badge cursor-pointer ${
                        severity.includes(s)
                          ? 'bg-primary-100 text-primary-800 ring-1 ring-primary-600'
                          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <label className="label">Maintenance</label>
                <div className="flex gap-2">
                  <button
                    onClick={() => updateFilters('in_maintenance', inMaintenance === 'true' ? null : 'true')}
                    className={`badge cursor-pointer ${
                      inMaintenance === 'true'
                        ? 'bg-blue-100 text-blue-800 ring-1 ring-blue-600'
                        : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                    }`}
                  >
                    In Maintenance
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Incidents Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Incident
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Severity
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Source
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Events
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Last Seen
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
                    No incidents found
                  </td>
                </tr>
              ) : (
                data?.items?.map((incident: Incident) => (
                  <tr key={incident.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <Link
                        to={`/incidents/${incident.id}`}
                        className="block"
                      >
                        <div className="text-sm font-medium text-gray-900 hover:text-primary-600">
                          {incident.title}
                        </div>
                        <div className="text-sm text-gray-500">
                          {incident.host && <span>{incident.host}</span>}
                          {incident.check_name && <span> / {incident.check_name}</span>}
                        </div>
                        {incident.is_in_maintenance && (
                          <span className="badge bg-blue-100 text-blue-800 mt-1">
                            In Maintenance
                          </span>
                        )}
                      </Link>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <SeverityBadge severity={incident.severity} />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <StatusBadge status={incident.status} />
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {incident.source_tool || '-'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {incident.event_count}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDistanceToNow(new Date(incident.last_seen_at), { addSuffix: true })}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {data && data.total_pages > 1 && (
          <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
            <div className="flex-1 flex justify-between sm:hidden">
              <button
                onClick={() => updateFilters('page', String(page - 1))}
                disabled={page === 1}
                className="btn-secondary"
              >
                Previous
              </button>
              <button
                onClick={() => updateFilters('page', String(page + 1))}
                disabled={page === data.total_pages}
                className="btn-secondary"
              >
                Next
              </button>
            </div>
            <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
              <div>
                <p className="text-sm text-gray-700">
                  Showing page <span className="font-medium">{page}</span> of{' '}
                  <span className="font-medium">{data.total_pages}</span>
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => updateFilters('page', String(page - 1))}
                  disabled={page === 1}
                  className="btn-secondary"
                >
                  <ChevronLeftIcon className="h-5 w-5" />
                </button>
                <button
                  onClick={() => updateFilters('page', String(page + 1))}
                  disabled={page === data.total_pages}
                  className="btn-secondary"
                >
                  <ChevronRightIcon className="h-5 w-5" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
