import { useCallback, useEffect, useState } from 'react'
import Card from '../ui/Card'
import Button from '../ui/Button'
import Input from '../ui/Input'
import Alert from '../ui/Alert'
import Badge from '../ui/Badge'
import {
  formFromSettings, loadGateUsage, saveGatePricing, saveGateSettings, settingsFromForm, withSubscriptionFeature,
} from '../../modules/ai/gateClient'

const CLASS_VARIANT = { free: 'high', local: 'high', subscription: 'high', paid: 'medium', unknown: 'warn' }
const money = (n, cur) => `${Number(n || 0).toFixed(4)} ${cur}`
const priceText = (p) => (p == null ? '—' : String(p))

/** Shows Alert errors / the two-step confirm for a save that raises what the gate allows. */
function SaveResult({ result, onConfirm, busy }) {
  if (!result) return null
  if (result.needsConfirm) {
    return (
      <Alert variant="error" title="Confirm: this lets the app spend more or run more by itself">
        <ul className="list-disc pl-5">{result.increases.map((line) => <li key={line}>{line}</li>)}</ul>
        <Button className="mt-3" onClick={onConfirm} disabled={busy}>Confirm and save</Button>
      </Alert>
    )
  }
  if (result.errors) return <Alert variant="error" title="Not saved">{result.errors.join('; ')}</Alert>
  if (result.ok) {
    return (
      <Alert variant="success">
        Saved.{(result.warnings || []).map((w) => <span key={w} className="block">{w}</span>)}
      </Alert>
    )
  }
  return null
}

function UsageBucket({ title, bucket, currency }) {
  return (
    <div className="rounded-lg border border-stone-200 p-3 text-sm dark:border-stone-700">
      <p className="font-medium">{title}</p>
      <p>Spend (estimate): {money(bucket.cost, currency)}</p>
      <p>Calls: {bucket.calls} ({bucket.paidCalls} paid, {bucket.subscriptionCalls || 0} on the Claude subscription)</p>
      <p>Refused: {bucket.refused}</p>
      {bucket.unpricedPaidCalls > 0 && <p className="text-xs text-red-600">{bucket.unpricedPaidCalls} paid calls had no known price.</p>}
    </div>
  )
}

function BreakdownTable({ title, data }) {
  const rows = Object.entries(data || {})
  if (!rows.length) return null
  return (
    <div className="overflow-x-auto">
      <p className="mb-1 text-sm font-medium">{title} (this month)</p>
      <table className="w-full text-left text-xs">
        <thead><tr><th>Name</th><th>Calls</th><th>Refused</th><th>Cost</th></tr></thead>
        <tbody>
          {rows.map(([name, b]) => (
            <tr key={name}><td>{name}</td><td>{b.calls}</td><td>{b.refused}</td><td>{Number(b.cost).toFixed(4)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PricingTable({ usage, reload }) {
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState({})
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const entries = usage.pricing?.entries || []
  const overrides = entries.filter((e) => e.origin === 'override')
  const stripped = (e) => ({
    provider: e.provider, model: e.model, class: e.class, inputPerMTok: e.inputPerMTok ?? null,
    outputPerMTok: e.outputPerMTok ?? null, source: e.source ?? null,
  })

  const send = async (list, confirm) => {
    setBusy(true)
    const r = await saveGatePricing(list, confirm).catch((e) => ({ errors: [e.message] }))
    setBusy(false)
    setResult(r)
    if (r.ok) { setEditing(null); reload() }
    return r
  }

  const candidate = () => {
    const price = (v) => (String(v ?? '').trim() === '' ? null : Number(v))
    const row = {
      provider: draft.provider, model: draft.model, class: draft.class,
      inputPerMTok: price(draft.inputPerMTok), outputPerMTok: price(draft.outputPerMTok), source: draft.source || null,
    }
    return [...overrides.filter((o) => !(o.provider === row.provider && o.model === row.model)).map(stripped), row]
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-stone-500">
        Unknown is treated as paid. Free or priced needs a source note (the provider&apos;s price page). Prices are per
        1M tokens in {usage.pricing?.currency}. Edits are kept in {usage.pricingOverridesFile}.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead><tr><th>Provider / model</th><th>Class</th><th>In</th><th>Out</th><th>Source</th><th /></tr></thead>
          <tbody>
            {entries.map((e) => {
              const key = `${e.provider}/${e.model}`
              const open = editing === key
              return (
                <tr key={key} className="align-top">
                  <td>{key}{e.origin === 'override' && <span className="ml-1 text-teal-700"> (edited)</span>}</td>
                  <td>
                    {open ? (
                      <select value={draft.class} onChange={(ev) => setDraft({ ...draft, class: ev.target.value })}>
                        {['free', 'local', 'paid', 'unknown'].map((c) => <option key={c}>{c}</option>)}
                      </select>
                    ) : <Badge variant={CLASS_VARIANT[e.class]}>{e.class}</Badge>}
                  </td>
                  <td>{open ? <input className="w-16" aria-label="input price" value={draft.inputPerMTok} onChange={(ev) => setDraft({ ...draft, inputPerMTok: ev.target.value })} /> : priceText(e.inputPerMTok)}</td>
                  <td>{open ? <input className="w-16" aria-label="output price" value={draft.outputPerMTok} onChange={(ev) => setDraft({ ...draft, outputPerMTok: ev.target.value })} /> : priceText(e.outputPerMTok)}</td>
                  <td>{open ? <input className="w-48" aria-label="source note" value={draft.source} placeholder="where this comes from" onChange={(ev) => setDraft({ ...draft, source: ev.target.value })} /> : (e.source || '—')}</td>
                  <td className="whitespace-nowrap">
                    {open ? (
                      <>
                        <Button variant="secondary" className="!text-xs" disabled={busy} onClick={() => send(candidate(), false)}>Save</Button>
                        <Button variant="ghost" className="!text-xs" onClick={() => { setEditing(null); setResult(null) }}>Cancel</Button>
                      </>
                    ) : (
                      <>
                        <Button variant="ghost" className="!text-xs" onClick={() => { setEditing(key); setResult(null); setDraft({ provider: e.provider, model: e.model, class: e.class, inputPerMTok: e.inputPerMTok ?? '', outputPerMTok: e.outputPerMTok ?? '', source: e.source ?? '' }) }}>Edit</Button>
                        {e.origin === 'override' && (
                          <Button variant="ghost" className="!text-xs" disabled={busy} onClick={() => send(overrides.filter((o) => o !== e).map(stripped), false)}>Reset</Button>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <SaveResult result={result} busy={busy} onConfirm={() => send(editing ? candidate() : [], true)} />
    </div>
  )
}

export default function AIBudgetPanel() {
  const [usage, setUsage] = useState(null)
  const [loadError, setLoadError] = useState(null)
  const [form, setForm] = useState(null)
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    try {
      const u = await loadGateUsage()
      setUsage(u)
      setForm((current) => current || formFromSettings(u.settings))
      setLoadError(null)
    } catch (e) {
      setLoadError(e.message)
    }
  }, [])

  useEffect(() => { reload() }, [reload])

  if (loadError) return <Alert variant="error" title="AI budget">{loadError}. The budget gate needs the app server (npm run serve).</Alert>
  if (!usage || !form) return <p className="text-sm text-stone-500">Loading AI budget…</p>

  const set = (key) => (e) => setForm({ ...form, [key]: e.target.value })
  const cur = usage.settings.currency

  const save = async (confirm) => {
    setBusy(true)
    const r = await saveGateSettings(settingsFromForm(form), confirm).catch((e) => ({ errors: [e.message] }))
    setBusy(false)
    setResult(r)
    if (r.ok) { setForm(formFromSettings(r.settings)); reload() }
  }

  return (
    <div className="space-y-6">
      <Card title="AI budget" description="Budget 0 = no paid calls; free and local models still run and are logged.">
        <div className="space-y-4">
          {usage.settings.error && <Alert variant="error" title="Settings file unusable">{usage.settings.error}. Paid calls are refused until you save.</Alert>}
          {!usage.settingsFileExists && <p className="text-xs text-stone-500">No settings file yet: budget 0, automatic AI tasks off.</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Input label="Daily limit" type="number" min="0" step="any" value={form.dailyLimit} onChange={set('dailyLimit')} />
            <Input label="Monthly limit" type="number" min="0" step="any" value={form.monthlyLimit} onChange={set('monthlyLimit')} />
            <Input label="Max paid calls per day (empty = none)" type="number" min="0" step="1" value={form.maxCallsDaily} onChange={set('maxCallsDaily')} />
            <Input label="Max paid calls per month (empty = none)" type="number" min="0" step="1" value={form.maxCallsMonthly} onChange={set('maxCallsMonthly')} />
            <Input label="Estimated output tokens per call" type="number" min="0" step="1" value={form.estimatedOutputTokens} onChange={set('estimatedOutputTokens')} />
            <Input label="Currency" value={form.currency} onChange={set('currency')} />
            <Input label="Timezone (IANA)" value={form.timezone} onChange={set('timezone')} placeholder="Europe/Belgrade" />
          </div>
          <label className="flex items-start gap-2 text-sm">
            <input type="checkbox" className="mt-1" checked={form.automationEnabled}
              onChange={(e) => setForm({ ...form, automationEnabled: e.target.checked })} />
            <span>Automatic AI tasks (scheduled pipeline, enrichment without --manual). Off by default; on needs a confirm.</span>
          </label>
          <div className="space-y-2 rounded-lg border border-stone-200 p-3 dark:border-stone-700">
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={form.subscriptionEnabled}
                onChange={(e) => setForm({ ...form, subscriptionEnabled: e.target.checked })} />
              <span>
                Claude Code on my flat Claude subscription: calls for {form.subscriptionFeatures.join(', ')} are not charged
                against the budget (cost 0, still logged). They use your plan&apos;s usage allowance and send the redacted ad and a
                profile summary to Anthropic. Off by default; on needs a confirm.
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input type="checkbox" className="mt-1" checked={form.subscriptionFeatures.includes('job-import')}
                onChange={(e) => setForm({ ...form, subscriptionFeatures: withSubscriptionFeature(form.subscriptionFeatures, 'job-import', e.target.checked) })} />
              <span>
                Also cover reading a job page&apos;s missing fields (Add job &gt; &quot;Extract the missing fields with AI&quot;, feature job-import). It sends the
                page text, with your name, e-mail addresses, phone numbers and links removed, to Anthropic, only after you confirm in that form. Adding it needs a confirm here.
              </span>
            </label>
            <Input label="Max subscription calls per day" type="number" min="1" step="1" value={form.subscriptionMaxCallsDaily}
              onChange={set('subscriptionMaxCallsDaily')} />
          </div>
          <p className="text-xs text-stone-500">
            Limits are in {cur}. A paid call also needs a known price below. Raising a limit, removing a call cap or
            turning automation on asks you to confirm before it is saved; lowering never does.
          </p>
          <Button onClick={() => { setResult(null); save(false) }} disabled={busy}>Save AI budget</Button>
          <SaveResult result={result} busy={busy} onConfirm={() => save(true)} />
        </div>
      </Card>

      <Card title="Models and prices">
        <PricingTable usage={usage} reload={reload} />
      </Card>

      <Card title="Gate usage" description="From the append-only ledger. Costs are estimates. Rows cannot be edited or deleted here.">
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <UsageBucket title={`Today (${usage.day})`} bucket={usage.today} currency={cur} />
            <UsageBucket title={`This month (${usage.month})`} bucket={usage.thisMonth} currency={cur} />
          </div>
          <BreakdownTable title="By provider / model" data={usage.byProvider} />
          <BreakdownTable title="By module" data={usage.byFeature} />
          <div className="overflow-x-auto">
            <p className="mb-1 text-sm font-medium">Last {usage.recent.length} calls</p>
            <table className="w-full text-left text-xs">
              <thead><tr><th>Time</th><th>Module</th><th>Provider / model</th><th>Class</th><th>Decision</th><th>Cost</th></tr></thead>
              <tbody>
                {usage.recent.map((r) => (
                  <tr key={r.id} title={r.reason || r.error || ''}>
                    <td>{r.ts?.slice(0, 19).replace('T', ' ')}</td><td>{r.feature}</td>
                    <td>{r.provider}/{r.model || '-'}</td><td>{r.class}</td>
                    <td>{r.decision}{r.decision === 'refused' && r.reason ? `: ${r.reason}` : ''}</td>
                    <td>{r.cost == null ? '—' : Number(r.cost).toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </Card>
    </div>
  )
}
