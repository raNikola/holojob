import Badge from '../ui/Badge'
import { fitScoreStyle } from '../../modules/jobs/fitScore'

const SIZE = { md: 'text-base', lg: 'text-2xl' }

/** The one Fit Score display: the number, coloured by its band, then the band label as a small chip, always on one line ("67 [Good]"). */
export default function FitScore({ score, label = '', size = 'md', emptyLabel = '—' }) {
  if (typeof score !== 'number') return <span className="text-stone-400">{emptyLabel}</span>
  const { variant, scoreClass } = fitScoreStyle(label)
  return (
    <div className="flex items-center gap-1.5">
      <span className={`font-semibold tabular-nums ${SIZE[size] || SIZE.md} ${scoreClass}`}>{score}</span>
      {label && <Badge variant={variant}>{label}</Badge>}
    </div>
  )
}
