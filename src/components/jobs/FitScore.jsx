import Badge from '../ui/Badge'
import { fitScoreStyle } from '../../modules/jobs/fitScore'

const SIZE = { md: 'text-base', lg: 'text-2xl' }

/** The one Fit Score display: the number, coloured by its band, with the band label. */
export default function FitScore({ score, label = '', size = 'md' }) {
  if (typeof score !== 'number') return <span className="text-stone-400">—</span>
  const { variant, scoreClass } = fitScoreStyle(label)
  return (
    <div className="flex flex-col items-start gap-0.5">
      <span className={`font-semibold tabular-nums ${SIZE[size] || SIZE.md} ${scoreClass}`}>{score}</span>
      {label && <Badge variant={variant}>{label}</Badge>}
    </div>
  )
}
