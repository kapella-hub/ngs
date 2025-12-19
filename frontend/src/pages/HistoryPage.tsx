import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  MagnifyingGlassIcon,
  FunnelIcon,
  ChartBarIcon,
  ClockIcon,
  ServerIcon,
  WrenchScrewdriverIcon,
} from '@heroicons/react/24/outline'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  AreaChart,
  Area,
} from 'recharts'
import { format, parseISO } from 'date-fns'
import clsx from 'clsx'
import { api } from '../api/client'
import { Link } from 'react-router-dom'

const SEVERITY_COLORS: Record<string, string> = {
  critical: '#dc2626',
  high: '#f97316',
  medium: '#eab308',
  low: '#3b82f6',
  info: '#6b7280',
}

interface TimelineData {
  incidents: Array<{
    period: string
    total: number
    critical: number
    high: number
    medium: number
    low: number
    info: number
  }>
  events: Array<{
    period: string
    total: number
    unique_incidents: number
  }>
  resolution: Array<{
    period: string
    avg_minutes: number | null
    count: number
  }>
  granularity: string
  days: number
}

interface TopHost {
  host: string
  incident_count: number
  open_count: number
  critical_high_count: number
  last_incident: string
}

interface TopService {
  service: string
  source_tool: string
  incident_count: number
  open_count: number
  affected_hosts: number
  last_incident: string
}

interface MTTRData {
  overall: {
    avg_minutes: number | null
    median_minutes: number | null
    p95_minutes: number | null
    resolved_count: number
  }
  by_severity: Array<{ severity: string; avg_minutes: number | null; count: number }>
  by_source: Array<{ source: string; avg_minutes: number | null; count: number }>
}

interface SearchResult {
  id: string
  fingerprint: string
  title: string
  source_tool: string
  host: string
  check_name: string
  severity: string
  status: string
  first_seen_at: string
  last_seen_at: string
  event_count: number
}

const TIME_RANGES = [
  { label: '7 days', days: 7, granularity: 'day' },
  { label: '14 days', days: 14, granularity: 'day' },
  { label: '30 days', days: 30, granularity: 'day' },
  { label: '90 days', days: 90, granularity: 'week' },
]

export default function HistoryPage() {
  const [timeRange, setTimeRange] = useState(TIME_RANGES[2])
  const [searchQuery, setSearchQuery] = useState('')
  const [searchFilters, setSearchFilters] = useState({
    status: '',
    severity: '',
    source: '',
  })
  const [activeTab, setActiveTab] = useState<'overview' | 'search'>('overview')

  // Fetch timeline data
  const { data: timeline, isLoading: timelineLoading } = useQuery<TimelineData>({
    queryKey: ['timeline', timeRange.days, timeRange.granularity],
    queryFn: async () => {
      const res = await api.get('/admin/stats/timeline', {
        params: { days: timeRange.days, granularity: timeRange.granularity },
      })
      return res.data
    },
  })

  // Fetch top hosts
  const { data: topHosts } = useQuery<{ hosts: TopHost[] }>({
    queryKey: ['top-hosts', timeRange.days],
    queryFn: async () => {
      const res = await api.get('/admin/stats/top-hosts', {
        params: { days: timeRange.days, limit: 10 },
      })
      return res.data
    },
  })

  // Fetch top services
  const { data: topServices } = useQuery<{ services: TopService[] }>({
    queryKey: ['top-services', timeRange.days],
    queryFn: async () => {
      const res = await api.get('/admin/stats/top-services', {
        params: { days: timeRange.days, limit: 10 },
      })
      return res.data
    },
  })

  // Fetch MTTR stats
  const { data: mttr } = useQuery<MTTRData>({
    queryKey: ['mttr', timeRange.days],
    queryFn: async () => {
      const res = await api.get('/admin/stats/mttr', {
        params: { days: timeRange.days },
      })
      return res.data
    },
  })

  // Fetch severity breakdown
  const { data: severityBreakdown } = useQuery<{ breakdown: Array<{ severity: string; status: string; count: number }> }>({
    queryKey: ['severity-breakdown'],
    queryFn: async () => {
      const res = await api.get('/admin/stats/severity')
      return res.data
    },
  })

  // Fetch sources breakdown
  const { data: sourcesBreakdown } = useQuery<{ sources: Array<{ source_tool: string; total: number; open: number }> }>({
    queryKey: ['sources-breakdown'],
    queryFn: async () => {
      const res = await api.get('/admin/stats/sources')
      return res.data
    },
  })

  // Search query
  const { data: searchResults, isLoading: searchLoading } = useQuery<{ results: SearchResult[]; total: number }>({
    queryKey: ['search', searchQuery, searchFilters, timeRange.days],
    queryFn: async () => {
      const res = await api.get('/admin/stats/search', {
        params: {
          q: searchQuery,
          days: timeRange.days,
          ...Object.fromEntries(Object.entries(searchFilters).filter(([_, v]) => v)),
        },
      })
      return res.data
    },
    enabled: activeTab === 'search' && searchQuery.length > 0,
  })

  // Format time for charts
  const formatPeriod = (period: string) => {
    if (!period) return ''
    try {
      const date = parseISO(period)
      if (timeRange.granularity === 'hour') {
        return format(date, 'MMM d HH:mm')
      } else if (timeRange.granularity === 'week') {
        return format(date, 'MMM d')
      }
      return format(date, 'MMM d')
    } catch {
      return period
    }
  }

  // Format minutes to human readable
  const formatMinutes = (minutes: number | null) => {
    if (minutes === null) return '-'
    if (minutes < 60) return `${Math.round(minutes)}m`
    if (minutes < 1440) return `${Math.round(minutes / 60)}h`
    return `${Math.round(minutes / 1440)}d`
  }

  // Prepare severity pie chart data
  const severityPieData = severityBreakdown?.breakdown
    ? Object.entries(
        severityBreakdown.breakdown.reduce((acc, item) => {
          acc[item.severity] = (acc[item.severity] || 0) + item.count
          return acc
        }, {} as Record<string, number>)
      ).map(([name, value]) => ({ name, value }))
    : []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">History & Analytics</h1>
          <p className="mt-1 text-sm text-gray-500">
            Historical incident data, trends, and search
          </p>
        </div>

        {/* Time Range Selector */}
        <div className="flex items-center space-x-2">
          {TIME_RANGES.map((range) => (
            <button
              key={range.days}
              onClick={() => setTimeRange(range)}
              className={clsx(
                'px-3 py-1.5 text-sm font-medium rounded-md',
                timeRange.days === range.days
                  ? 'bg-primary-600 text-white'
                  : 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50'
              )}
            >
              {range.label}
            </button>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('overview')}
            className={clsx(
              'py-4 px-1 border-b-2 font-medium text-sm',
              activeTab === 'overview'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            )}
          >
            <ChartBarIcon className="h-5 w-5 inline mr-2" />
            Overview
          </button>
          <button
            onClick={() => setActiveTab('search')}
            className={clsx(
              'py-4 px-1 border-b-2 font-medium text-sm',
              activeTab === 'search'
                ? 'border-primary-500 text-primary-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            )}
          >
            <MagnifyingGlassIcon className="h-5 w-5 inline mr-2" />
            Search
          </button>
        </nav>
      </div>

      {activeTab === 'overview' && (
        <div className="space-y-6">
          {/* MTTR Stats Cards */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center">
                <ClockIcon className="h-8 w-8 text-primary-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-gray-500">Avg Resolution Time</p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {formatMinutes(mttr?.overall.avg_minutes ?? null)}
                  </p>
                </div>
              </div>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center">
                <ClockIcon className="h-8 w-8 text-blue-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-gray-500">Median Resolution</p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {formatMinutes(mttr?.overall.median_minutes ?? null)}
                  </p>
                </div>
              </div>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center">
                <ClockIcon className="h-8 w-8 text-orange-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-gray-500">P95 Resolution</p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {formatMinutes(mttr?.overall.p95_minutes ?? null)}
                  </p>
                </div>
              </div>
            </div>
            <div className="bg-white rounded-lg shadow p-4">
              <div className="flex items-center">
                <ChartBarIcon className="h-8 w-8 text-green-500" />
                <div className="ml-4">
                  <p className="text-sm font-medium text-gray-500">Resolved Incidents</p>
                  <p className="text-2xl font-semibold text-gray-900">
                    {mttr?.overall.resolved_count ?? 0}
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Incidents Timeline Chart */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-medium text-gray-900 mb-4">Incidents Over Time</h3>
            {timelineLoading ? (
              <div className="h-64 flex items-center justify-center">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={300}>
                <AreaChart data={timeline?.incidents || []}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="period" tickFormatter={formatPeriod} fontSize={12} />
                  <YAxis fontSize={12} />
                  <Tooltip
                    labelFormatter={formatPeriod}
                    contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb' }}
                  />
                  <Legend />
                  <Area type="monotone" dataKey="critical" stackId="1" stroke={SEVERITY_COLORS.critical} fill={SEVERITY_COLORS.critical} name="Critical" />
                  <Area type="monotone" dataKey="high" stackId="1" stroke={SEVERITY_COLORS.high} fill={SEVERITY_COLORS.high} name="High" />
                  <Area type="monotone" dataKey="medium" stackId="1" stroke={SEVERITY_COLORS.medium} fill={SEVERITY_COLORS.medium} name="Medium" />
                  <Area type="monotone" dataKey="low" stackId="1" stroke={SEVERITY_COLORS.low} fill={SEVERITY_COLORS.low} name="Low" />
                  <Area type="monotone" dataKey="info" stackId="1" stroke={SEVERITY_COLORS.info} fill={SEVERITY_COLORS.info} name="Info" />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Events and Resolution Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Events Over Time */}
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Alert Events</h3>
              <ResponsiveContainer width="100%" height={250}>
                <LineChart data={timeline?.events || []}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="period" tickFormatter={formatPeriod} fontSize={12} />
                  <YAxis fontSize={12} />
                  <Tooltip labelFormatter={formatPeriod} />
                  <Legend />
                  <Line type="monotone" dataKey="total" stroke="#3b82f6" name="Total Events" strokeWidth={2} />
                  <Line type="monotone" dataKey="unique_incidents" stroke="#22c55e" name="Unique Incidents" strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>

            {/* Severity Breakdown Pie */}
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Severity Distribution</h3>
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={severityPieData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={2}
                    dataKey="value"
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  >
                    {severityPieData.map((entry) => (
                      <Cell
                        key={entry.name}
                        fill={SEVERITY_COLORS[entry.name as keyof typeof SEVERITY_COLORS] || '#6b7280'}
                      />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* MTTR by Severity and Source */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* MTTR by Severity */}
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">MTTR by Severity</h3>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={mttr?.by_severity || []} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" fontSize={12} />
                  <YAxis type="category" dataKey="severity" fontSize={12} width={80} />
                  <Tooltip formatter={(value: number) => formatMinutes(value)} />
                  <Bar dataKey="avg_minutes" name="Avg Resolution (min)">
                    {(mttr?.by_severity || []).map((entry) => (
                      <Cell
                        key={entry.severity}
                        fill={SEVERITY_COLORS[entry.severity as keyof typeof SEVERITY_COLORS] || '#6b7280'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {/* Sources Breakdown */}
            <div className="bg-white rounded-lg shadow p-6">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Incidents by Source</h3>
              <ResponsiveContainer width="100%" height={250}>
                <BarChart data={sourcesBreakdown?.sources || []} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" fontSize={12} />
                  <YAxis type="category" dataKey="source_tool" fontSize={12} width={100} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="open" name="Open" fill="#dc2626" stackId="a" />
                  <Bar dataKey="total" name="Total" fill="#3b82f6" stackId="b" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top Hosts and Services Tables */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Top Hosts */}
            <div className="bg-white rounded-lg shadow">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center">
                <ServerIcon className="h-5 w-5 text-gray-400 mr-2" />
                <h3 className="text-lg font-medium text-gray-900">Top Hosts</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Host</th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Incidents</th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Open</th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Critical/High</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {topHosts?.hosts.map((host) => (
                      <tr key={host.host} className="hover:bg-gray-50">
                        <td className="px-6 py-3 text-sm font-medium text-gray-900 truncate max-w-xs">
                          {host.host}
                        </td>
                        <td className="px-6 py-3 text-sm text-gray-500 text-right">{host.incident_count}</td>
                        <td className="px-6 py-3 text-sm text-right">
                          {host.open_count > 0 ? (
                            <span className="text-red-600 font-medium">{host.open_count}</span>
                          ) : (
                            <span className="text-gray-400">0</span>
                          )}
                        </td>
                        <td className="px-6 py-3 text-sm text-right">
                          {host.critical_high_count > 0 ? (
                            <span className="text-orange-600 font-medium">{host.critical_high_count}</span>
                          ) : (
                            <span className="text-gray-400">0</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Top Services */}
            <div className="bg-white rounded-lg shadow">
              <div className="px-6 py-4 border-b border-gray-200 flex items-center">
                <WrenchScrewdriverIcon className="h-5 w-5 text-gray-400 mr-2" />
                <h3 className="text-lg font-medium text-gray-900">Top Services/Checks</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Service</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Incidents</th>
                      <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Hosts</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {topServices?.services.map((svc, idx) => (
                      <tr key={`${svc.service}-${idx}`} className="hover:bg-gray-50">
                        <td className="px-6 py-3 text-sm font-medium text-gray-900 truncate max-w-xs">
                          {svc.service}
                        </td>
                        <td className="px-6 py-3 text-sm text-gray-500">{svc.source_tool || '-'}</td>
                        <td className="px-6 py-3 text-sm text-gray-500 text-right">{svc.incident_count}</td>
                        <td className="px-6 py-3 text-sm text-gray-500 text-right">{svc.affected_hosts}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === 'search' && (
        <div className="space-y-6">
          {/* Search Bar */}
          <div className="bg-white rounded-lg shadow p-4">
            <div className="flex flex-col md:flex-row gap-4">
              <div className="flex-1">
                <div className="relative">
                  <MagnifyingGlassIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search incidents by host, service, title, or fingerprint..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="block w-full pl-10 pr-3 py-2 border border-gray-300 rounded-md leading-5 bg-white placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-primary-500 focus:border-primary-500"
                  />
                </div>
              </div>

              {/* Filters */}
              <div className="flex items-center gap-2">
                <FunnelIcon className="h-5 w-5 text-gray-400" />
                <select
                  value={searchFilters.status}
                  onChange={(e) => setSearchFilters({ ...searchFilters, status: e.target.value })}
                  className="border border-gray-300 rounded-md py-2 px-3 text-sm focus:ring-primary-500 focus:border-primary-500"
                >
                  <option value="">All Status</option>
                  <option value="open">Open</option>
                  <option value="acknowledged">Acknowledged</option>
                  <option value="resolved">Resolved</option>
                  <option value="suppressed">Suppressed</option>
                </select>
                <select
                  value={searchFilters.severity}
                  onChange={(e) => setSearchFilters({ ...searchFilters, severity: e.target.value })}
                  className="border border-gray-300 rounded-md py-2 px-3 text-sm focus:ring-primary-500 focus:border-primary-500"
                >
                  <option value="">All Severity</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                  <option value="info">Info</option>
                </select>
                <select
                  value={searchFilters.source}
                  onChange={(e) => setSearchFilters({ ...searchFilters, source: e.target.value })}
                  className="border border-gray-300 rounded-md py-2 px-3 text-sm focus:ring-primary-500 focus:border-primary-500"
                >
                  <option value="">All Sources</option>
                  {sourcesBreakdown?.sources.map((s) => (
                    <option key={s.source_tool} value={s.source_tool}>
                      {s.source_tool}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>

          {/* Search Results */}
          {searchQuery.length > 0 && (
            <div className="bg-white rounded-lg shadow">
              <div className="px-6 py-4 border-b border-gray-200">
                <h3 className="text-lg font-medium text-gray-900">
                  {searchLoading ? 'Searching...' : `${searchResults?.total || 0} results found`}
                </h3>
              </div>
              {searchLoading ? (
                <div className="p-8 flex justify-center">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Title</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Host</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Source</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Severity</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Last Seen</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Events</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {searchResults?.results.map((incident) => (
                        <tr key={incident.id} className="hover:bg-gray-50">
                          <td className="px-6 py-4 text-sm">
                            <Link
                              to={`/incidents/${incident.id}`}
                              className="text-primary-600 hover:text-primary-900 font-medium"
                            >
                              {incident.title || incident.check_name || '-'}
                            </Link>
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-500 truncate max-w-xs">
                            {incident.host || '-'}
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-500">{incident.source_tool || '-'}</td>
                          <td className="px-6 py-4 text-sm">
                            <span
                              className={clsx('px-2 py-1 rounded-full text-xs font-medium', {
                                'bg-red-100 text-red-800': incident.severity === 'critical',
                                'bg-orange-100 text-orange-800': incident.severity === 'high',
                                'bg-yellow-100 text-yellow-800': incident.severity === 'medium',
                                'bg-blue-100 text-blue-800': incident.severity === 'low',
                                'bg-gray-100 text-gray-800': incident.severity === 'info',
                              })}
                            >
                              {incident.severity}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-sm">
                            <span
                              className={clsx('px-2 py-1 rounded-full text-xs font-medium', {
                                'bg-red-100 text-red-800': incident.status === 'open',
                                'bg-orange-100 text-orange-800': incident.status === 'acknowledged',
                                'bg-green-100 text-green-800': incident.status === 'resolved',
                                'bg-gray-100 text-gray-800': incident.status === 'suppressed',
                              })}
                            >
                              {incident.status}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-500">
                            {incident.last_seen_at
                              ? format(parseISO(incident.last_seen_at), 'MMM d, HH:mm')
                              : '-'}
                          </td>
                          <td className="px-6 py-4 text-sm text-gray-500">{incident.event_count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {searchQuery.length === 0 && (
            <div className="bg-white rounded-lg shadow p-12 text-center">
              <MagnifyingGlassIcon className="mx-auto h-12 w-12 text-gray-400" />
              <h3 className="mt-2 text-sm font-medium text-gray-900">Search incidents</h3>
              <p className="mt-1 text-sm text-gray-500">
                Enter a search term to find incidents by host, service, title, or fingerprint.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
