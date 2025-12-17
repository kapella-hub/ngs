import clsx from 'clsx'
import { IncidentStatus } from '../types'

interface StatusBadgeProps {
  status: IncidentStatus
  size?: 'sm' | 'md'
}

const statusStyles: Record<IncidentStatus, string> = {
  open: 'bg-red-100 text-red-800',
  acknowledged: 'bg-yellow-100 text-yellow-800',
  resolved: 'bg-green-100 text-green-800',
  suppressed: 'bg-gray-100 text-gray-800',
}

export default function StatusBadge({ status, size = 'sm' }: StatusBadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full font-medium capitalize',
        statusStyles[status],
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm'
      )}
    >
      {status}
    </span>
  )
}
