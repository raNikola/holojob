// The red asterisk after a required field's label. The field itself carries
// aria-required, so the mark is hidden from screen readers.
export default function RequiredMark() {
  return <span aria-hidden="true" className="ml-0.5 text-red-500">*</span>
}

export function RequiredNote() {
  return <p className="mb-4 text-xs text-stone-500 dark:text-stone-400"><span aria-hidden="true" className="text-red-500">*</span> Required</p>
}
