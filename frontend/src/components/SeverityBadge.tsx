import clsx from 'clsx'
import { Severity } from '../types'

interface SeverityBadgeProps {
  severity: Severity
  size?: 'sm' | 'md'
}

const severityStyles: Record<Severity, string> = {
  critical: 'bg-red-100 text-red-800',
  high: 'bg-orange-100 text-orange-800',
  medium: 'bg-yellow-100 text-yellow-800',
  low: 'bg-green-100 text-green-800',
  info: 'bg-gray-100 text-gray-800',
}

export default function SeverityBadge({ severity, size = 'sm' }: SeverityBadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full font-medium capitalize',
        severityStyles[severity],
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-sm'
      )}
    >
      {severity}
    </span>
  )
}
