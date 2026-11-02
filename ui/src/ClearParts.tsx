import type { ReactNode } from 'react';
import { LAYERS, LENGTHS, PLAN_ORDER, PLANS, STATE_TONES, STATE_WORDS } from './vocabulary';
import type { BotState, Check, LayerId, Plan } from './vocabulary';

/* Shared design 2a pieces for the dashboard and the in-game widget. Presentational only:
   every action goes back through a callback, never straight to the engine. */

export function StateBadge({ state, children }: { state: BotState; children?: ReactNode }) {
  return <span className="c-badge" data-tone={STATE_TONES[state]}>{children ?? STATE_WORDS[state]}</span>;
}

export function CheckList({ checks, onAction, disabled }: {
  checks: Check[]; onAction?(action: NonNullable<Check['action']>): void; disabled?: boolean;
}) {
  return <ul className="c-checks">{checks.map(check => <li key={check.id} className={check.ok ? 'ok' : 'bad'}>
    <span className="c-mark" aria-hidden="true">{check.ok ? '✓' : '!'}</span>
    <span className="c-what">{check.label}<span className="c-sr">{check.ok ? ': done' : ': missing'}</span></span>
    {!check.ok && check.fix && <span className="c-fix">{check.fix}</span>}
    {!check.ok && check.action && onAction && <button className="c-btn small" disabled={disabled}
      onClick={() => onAction(check.action!)}>Bring game to front</button>}
  </li>)}</ul>;
}

/** The one thing to fix next, under the Start button. */
export function NextCheck({ blocker, onAction, disabled }: {
  blocker: Check | null; onAction?(action: NonNullable<Check['action']>): void; disabled?: boolean;
}) {
  if (!blocker) return <p className="c-next ok"><span className="c-mark" aria-hidden="true">✓</span> All checks pass.</p>;
  return <p className="c-next bad"><span className="c-mark" aria-hidden="true">!</span>
    <span><b>{blocker.label}</b> {blocker.fix}</span>
    {blocker.action && onAction && <button className="c-btn small" disabled={disabled} onClick={() => onAction(blocker.action!)}>Bring game to front</button>}
  </p>;
}

/** Large radio cards (dashboard) or a compact segmented row (widget). */
export function PlanPicker({ plan, onPlan, disabled, compact, available }: {
  plan: Plan; onPlan(plan: Plan): void; disabled?: boolean; compact?: boolean;
  /** Plans that cannot start in this session are shown disabled with their reason. */
  available?: Partial<Record<Plan, string>>;
}) {
  return <div className={compact ? 'c-seg' : 'c-plans'} role="radiogroup" aria-label="What to do">
    {PLAN_ORDER.map(key => {
      const blocked = available?.[key];
      return <button key={key} role="radio" aria-checked={plan === key} disabled={disabled || Boolean(blocked)}
        title={blocked ?? PLANS[key].note} onClick={() => onPlan(key)}>
        {compact ? PLANS[key].short : <><b>{PLANS[key].title}</b><span>{blocked ?? PLANS[key].note}</span></>}
      </button>;
    })}
  </div>;
}

export interface LoopOption { id: string; name: string; stops: number }

/** Previous/next buttons rather than a select: the widget window never takes focus, so native popups never open. */
export function LoopChooser({ plan, loops, selected, onSelect, disabled }: {
  plan: Plan; loops: LoopOption[] | undefined; selected: string | null; onSelect(id: string): void; disabled?: boolean;
}) {
  if (plan === 'platform') return <p className="c-quiet">Uses the platform you stand on.</p>;
  if (plan === 'watch') return <p className="c-quiet">No path needed.</p>;
  if (!loops) return <p className="c-quiet">Checking saved loops…</p>;
  if (!loops.length) return <p className="c-quiet">No saved loop on this map. Build one in Maps.</p>;
  const index = Math.max(0, loops.findIndex(loop => loop.id === selected));
  const current = loops.find(loop => loop.id === selected);
  const step = (by: number) => onSelect(loops[(index + by + loops.length) % loops.length].id);
  return <div className="c-chooser" role="group" aria-label="Saved loop">
    <button className="c-btn icon" aria-label="Previous loop" disabled={disabled} onClick={() => step(current ? -1 : 0)}>‹</button>
    <span title={current?.name}>{current ? <><b>{current.name}</b> <small>{current.stops} stops</small></> : 'Choose a loop'}</span>
    <button className="c-btn icon" aria-label="Next loop" disabled={disabled} onClick={() => step(current ? 1 : 0)}>›</button>
  </div>;
}

export function LengthPicker({ plan, minutes, onMinutes, disabled }: {
  plan: Plan; minutes: number; onMinutes(minutes: number): void; disabled?: boolean;
}) {
  if (plan === 'watch') return <p className="c-quiet">Runs until you stop it.</p>;
  return <div className="c-seg" role="radiogroup" aria-label="How long">
    {LENGTHS.map(value => <button key={value} role="radio" aria-checked={minutes === value} disabled={disabled}
      onClick={() => onMinutes(value)}>{value} min</button>)}
  </div>;
}

export function LayerToggles({ values, onToggle }: { values: Record<LayerId, boolean>; onToggle(id: LayerId): void }) {
  return <div className="c-layers" role="group" aria-label="Drawings on the game">
    {LAYERS.map(layer => <button key={layer.id} aria-pressed={values[layer.id]} onClick={() => onToggle(layer.id)}>
      <span className="c-switch" aria-hidden="true" />{layer.label}</button>)}
  </div>;
}

export function Meter({ label, kind, percent, threshold }: {
  label: string; kind: 'hp' | 'mp'; percent: number | null | undefined; threshold: number;
}) {
  const known = typeof percent === 'number';
  const value = known ? Math.max(0, Math.min(100, percent)) : 0;
  return <div className={`c-gauge ${kind} ${known && value < threshold + 10 ? 'low' : ''}`} title={`Potion at ${threshold}%`}>
    <span className="c-g-label">{label}</span>
    <span className="c-g-bar" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
      aria-valuenow={known ? Math.round(value) : undefined} aria-valuetext={known ? `${Math.round(value)}%` : 'Not read yet'}>
      <i style={{ width: `${value}%` }} /><b style={{ left: `${threshold}%` }} aria-hidden="true" />
    </span>
    <span className="c-g-val">{known ? `${Math.round(value)}%` : '—'}</span>
  </div>;
}

/** A key the operator can click to rebind. */
export function KeyCap({ label, value, capturing, onClick, disabled }: {
  label: string; value: string | null; capturing?: boolean; onClick?(): void; disabled?: boolean;
}) {
  return <button className={`c-keycap ${value ? '' : 'empty'}`} aria-pressed={Boolean(capturing)} disabled={disabled || !onClick}
    aria-label={`${label} key: ${value || 'none'}${onClick ? '. Change' : ''}`} onClick={onClick}>
    {capturing ? 'Press a key…' : value ? displayKey(value) : 'None'}
  </button>;
}

const KEY_NAMES: Record<string, string> = { ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', space: 'Space', insert: 'Insert',
  delete: 'Delete', home: 'Home', end: 'End', pageup: 'Page Up', pagedown: 'Page Down', left: '←', right: '→', up: '↑', down: '↓',
  pause: 'Pause', scrolllock: 'Scroll Lock' };
/** config.toml key names ("insert", "f8", "a") as they read on a keyboard. */
export function displayKey(key: string): string {
  const k = key.toLowerCase();
  return KEY_NAMES[k] ?? (/^f\d{1,2}$/.test(k) ? k.toUpperCase() : k.length === 1 ? k.toUpperCase() : key);
}
