import { useQuery } from '@tanstack/react-query'
import {
  ExclamationTriangleIcon,
  CheckCircleIcon,
  ClockIcon,
  WrenchScrewdriverIcon,
} from '@heroicons/react/24/outline'
import { Link } from 'react-router-dom'
import { adminApi, incidentsApi } from '../api/client'
import { Incident } from '../types'
import SeverityBadge from '../components/SeverityBadge'
import StatusBadge from '../components/StatusBadge'

export default function DashboardPage() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: adminApi.getStats,
    refetchInterval: 30000,
  })

  const { data: recentIncidents } = useQuery({
    queryKey: ['incidents', 'recent'],
    queryFn: () => incidentsApi.list({ page_size: 10, status: ['open', 'acknowledged'] }),
    refetchInterval: 30000,
  })

  const statCards = [
    {
      name: 'Open Incidents',
      value: stats?.incidents?.open || 0,
      icon: ExclamationTriangleIcon,
      color: 'text-red-600',
      bgColor: 'bg-red-100',
      href: '/incidents?status=open',
    },
    {
      name: 'Acknowledged',
      value: stats?.incidents?.acknowledged || 0,
      icon: ClockIcon,
      color: 'text-yellow-600',
      bgColor: 'bg-yellow-100',
      href: '/incidents?status=acknowledged',
    },
    {
      name: 'Resolved (24h)',
      value: stats?.incidents?.resolved || 0,
      icon: CheckCircleIcon,
      color: 'text-green-600',
      bgColor: 'bg-green-100',
      href: '/incidents?status=resolved',
    },
    {
      name: 'In Maintenance',
      value: stats?.incidents?.in_maintenance || 0,
      icon: WrenchScrewdriverIcon,
      color: 'text-blue-600',
      bgColor: 'bg-blue-100',
      href: '/incidents?in_maintenance=true',
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-1 text-sm text-gray-500">
          Overview of your alert noise reduction platform
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((stat) => (
          <Link
            key={stat.name}
            to={stat.href}
            className="card p-6 hover:shadow-md transition-shadow"
          >
            <div className="flex items-center">
              <div className={`${stat.bgColor} rounded-lg p-3`}>
                <stat.icon className={`h-6 w-6 ${stat.color}`} />
              </div>
              <div className="ml-4">
                <p className="text-sm font-medium text-gray-500">{stat.name}</p>
                <p className="text-2xl font-semibold text-gray-900">{stat.value}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* Activity Summary */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recent Incidents */}
        <div className="card">
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-medium text-gray-900">Active Incidents</h2>
              <Link to="/incidents" className="text-sm text-primary-600 hover:text-primary-700">
                View all
              </Link>
            </div>
          </div>
          <div className="divide-y divide-gray-200">
            {recentIncidents?.items?.length === 0 ? (
              <div className="px-6 py-8 text-center text-gray-500">
                <CheckCircleIcon className="mx-auto h-12 w-12 text-green-400" />
                <p className="mt-2">No active incidents</p>
              </div>
            ) : (
              recentIncidents?.items?.slice(0, 5).map((incident: Incident) => (
                <Link
                  key={incident.id}
                  to={`/incidents/${incident.id}`}
                  className="block px-6 py-4 hover:bg-gray-50"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {incident.title}
                      </p>
                      <div className="flex items-center gap-2 mt-1">
                        <SeverityBadge severity={incident.severity} />
                        <StatusBadge status={incident.status} />
                        {incident.is_in_maintenance && (
                          <span className="badge bg-blue-100 text-blue-800">Maintenance</span>
                        )}
                      </div>
                    </div>
                    <div className="ml-4 text-right">
                      <p className="text-sm text-gray-500">
                        {incident.event_count} events
                      </p>
                    </div>
                  </div>
                </Link>
              ))
            )}
          </div>
        </div>

        {/* Quick Stats */}
        <div className="card">
          <div className="px-6 py-4 border-b border-gray-200">
            <h2 className="text-lg font-medium text-gray-900">Last 24 Hours</h2>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-sm text-gray-500">New Incidents</p>
                <p className="text-3xl font-bold text-gray-900">
                  {stats?.last_24h?.new_incidents || 0}
                </p>
              </div>
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-sm text-gray-500">New Events</p>
                <p className="text-3xl font-bold text-gray-900">
                  {stats?.last_24h?.new_events || 0}
                </p>
              </div>
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-sm text-gray-500">Total Emails</p>
                <p className="text-3xl font-bold text-gray-900">
                  {stats?.emails?.total || 0}
                </p>
              </div>
              <div className="bg-gray-50 rounded-lg p-4">
                <p className="text-sm text-gray-500">Quarantined</p>
                <p className="text-3xl font-bold text-gray-900">
                  {stats?.emails?.quarantined || 0}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
