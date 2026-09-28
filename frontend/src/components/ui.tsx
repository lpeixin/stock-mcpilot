/**
 * 通用 UI 原子组件。
 *
 * 集中在这里的目的只有一个：让全应用只有一套边框、圆角、间距和空态写法。
 * 改造前每个页面各写一套，导致同样的卡片有三种 padding、两种圆角。
 */

import type { ReactNode } from 'react'

// ------------------------------------------------------------------ 卡片

interface CardProps {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children: ReactNode
  className?: string
  /** 去掉内边距（表格类内容自己控制）。 */
  flush?: boolean
}

export const Card: React.FC<CardProps> = ({
  title,
  subtitle,
  actions,
  children,
  className = '',
  flush = false,
}) => (
  <section className={`rounded-xl border border-slate-200 bg-white ${className}`}>
    {title || actions ? (
      <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="truncate text-sm font-medium text-slate-800">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </header>
    ) : null}
    <div className={flush ? '' : 'px-4 py-3'}>{children}</div>
  </section>
)

// ------------------------------------------------------------------ 状态

export const Spinner: React.FC<{ className?: string }> = ({ className = 'h-4 w-4' }) => (
  <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
    <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
  </svg>
)

export const EmptyState: React.FC<{ text: string; hint?: string; compact?: boolean }> = ({
  text,
  hint,
  compact = false,
}) => (
  <div
    className={`flex flex-col items-center justify-center text-center ${compact ? 'py-6' : 'py-10'}`}
  >
    <p className="text-xs text-slate-400">{text}</p>
    {hint ? <p className="mt-1 text-[11px] text-slate-300">{hint}</p> : null}
  </div>
)

export const ErrorBanner: React.FC<{ message: string; onRetry?: () => void; retryText?: string }> = ({
  message,
  onRetry,
  retryText = '重试',
}) => (
  <div className="flex items-start justify-between gap-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2">
    <p className="text-xs leading-relaxed text-red-700">{message}</p>
    {onRetry ? (
      <button
        type="button"
        onClick={onRetry}
        className="shrink-0 rounded border border-red-200 bg-white px-2 py-0.5 text-[11px] text-red-700 transition hover:bg-red-100"
      >
        {retryText}
      </button>
    ) : null}
  </div>
)

export const Skeleton: React.FC<{ className?: string }> = ({ className = 'h-4 w-full' }) => (
  <div className={`animate-pulse rounded bg-slate-100 ${className}`} />
)

// ------------------------------------------------------------------ 数据展示

export const Stat: React.FC<{
  label: string
  value: ReactNode
  hint?: ReactNode
  valueClass?: string
}> = ({ label, value, hint, valueClass = 'text-slate-900' }) => (
  <div className="min-w-0">
    <div className="truncate text-[11px] text-slate-400">{label}</div>
    <div className={`mt-0.5 truncate text-sm tabular-nums ${valueClass}`}>{value}</div>
    {hint ? <div className="mt-0.5 truncate text-[11px] text-slate-400">{hint}</div> : null}
  </div>
)

export const StatGrid: React.FC<{ children: ReactNode; columns?: string }> = ({
  children,
  columns = 'grid-cols-2 sm:grid-cols-3 lg:grid-cols-4',
}) => <div className={`grid gap-x-4 gap-y-3 ${columns}`}>{children}</div>

export const Badge: React.FC<{
  children: ReactNode
  tone?: 'neutral' | 'up' | 'down' | 'info' | 'warn'
  className?: string
}> = ({ children, tone = 'neutral', className = '' }) => {
  const tones: Record<string, string> = {
    neutral: 'bg-slate-100 text-slate-600',
    up: 'bg-red-50 text-[#d93f4c]',
    down: 'bg-emerald-50 text-[#1f9d63]',
    info: 'bg-blue-50 text-blue-700',
    warn: 'bg-amber-50 text-amber-700',
  }
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] leading-none ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  )
}

// ------------------------------------------------------------------ 控件

interface SegmentedProps<T extends string> {
  value: T
  options: { value: T; label: ReactNode; title?: string }[]
  onChange: (value: T) => void
  className?: string
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  className = '',
}: SegmentedProps<T>) {
  return (
    <div className={`inline-flex items-center gap-0.5 rounded-md bg-slate-100 p-0.5 ${className}`}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          title={option.title}
          onClick={() => onChange(option.value)}
          className={`rounded px-2 py-0.5 text-xs transition ${
            value === option.value
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-500 hover:text-slate-800'
          }`}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export const Toggle: React.FC<{
  checked: boolean
  onChange: (checked: boolean) => void
  label?: ReactNode
  disabled?: boolean
}> = ({ checked, onChange, label, disabled = false }) => (
  <label
    className={`flex items-center gap-2 text-xs ${
      disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'
    }`}
  >
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-4 w-7 shrink-0 rounded-full transition ${
        checked ? 'bg-blue-600' : 'bg-slate-300'
      }`}
    >
      <span
        className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all ${
          checked ? 'left-3.5' : 'left-0.5'
        }`}
      />
    </button>
    {label ? <span className="text-slate-600">{label}</span> : null}
  </label>
)

export const Button: React.FC<{
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  disabled?: boolean
  type?: 'button' | 'submit'
  className?: string
  title?: string
}> = ({
  children,
  onClick,
  variant = 'secondary',
  size = 'md',
  disabled = false,
  type = 'button',
  className = '',
  title,
}) => {
  const variants: Record<string, string> = {
    primary: 'bg-blue-600 text-white hover:bg-blue-700 border-transparent',
    secondary: 'bg-white text-slate-700 hover:bg-slate-50 border-slate-300',
    ghost: 'bg-transparent text-slate-600 hover:bg-slate-100 border-transparent',
    danger: 'bg-white text-red-600 hover:bg-red-50 border-red-200',
  }
  const sizes: Record<string, string> = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1.5 text-xs',
  }
  return (
    <button
      type={type}
      title={title}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md border transition disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${sizes[size]} ${className}`}
    >
      {children}
    </button>
  )
}

// ------------------------------------------------------------------ 表单

export const Field: React.FC<{
  label: string
  hint?: ReactNode
  children: ReactNode
  className?: string
}> = ({ label, hint, children, className = '' }) => (
  <div className={className}>
    <label className="mb-1 block text-xs font-medium text-slate-600">{label}</label>
    {children}
    {hint ? <p className="mt-1 text-[11px] leading-relaxed text-slate-400">{hint}</p> : null}
  </div>
)

export const inputClass =
  'w-full rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-800 outline-none transition placeholder:text-slate-300 focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:bg-slate-50 disabled:text-slate-400'

export const selectClass = `${inputClass} pr-6`
