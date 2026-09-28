/**
 * 财务报表：年报 / 季报切换 + 关键科目表。
 *
 * 比率字段（利润率、ROE、同比）后端给的是小数（0.2531），所以用 `fmtRatioPct`；
 * 金额字段用 `fmtAmount`（自动带 亿/万 量级）。两者不能混用 —— 改造前把
 * 利润率当百分数直接显示，结果 0.25 显示成 "0.25%"。
 */

import { Fragment, useState } from 'react'
import type { FinancialPeriod, Financials } from '../api/types'
import type { TranslateFn } from '../i18n'
import { signedPct, trendClass } from '../theme'
import { fmtAmount, fmtNum, fmtRatioPct } from '../utils/format'
import { Card, EmptyState, Segmented } from './ui'

type Mode = 'annual' | 'quarterly'
type Kind = 'money' | 'ratio' | 'number'

interface Item {
  field: string
  labelKey: string
  kind: Kind
  /** 单独成组，不并入三大表。 */
  group: 'income' | 'balance' | 'cashflow' | 'derived'
}

const ITEMS: Item[] = [
  { field: 'revenue', labelKey: 'financials.revenue', kind: 'money', group: 'income' },
  { field: 'gross_profit', labelKey: 'financials.grossProfit', kind: 'money', group: 'income' },
  { field: 'operating_income', labelKey: 'financials.operatingIncome', kind: 'money', group: 'income' },
  { field: 'net_income', labelKey: 'financials.netIncome', kind: 'money', group: 'income' },
  { field: 'diluted_eps', labelKey: 'financials.eps', kind: 'number', group: 'income' },
  { field: 'rnd', labelKey: 'financials.rnd', kind: 'money', group: 'income' },
  { field: 'sga', labelKey: 'financials.sga', kind: 'money', group: 'income' },

  { field: 'total_assets', labelKey: 'financials.totalAssets', kind: 'money', group: 'balance' },
  { field: 'total_liabilities', labelKey: 'financials.totalLiabilities', kind: 'money', group: 'balance' },
  { field: 'equity', labelKey: 'financials.equity', kind: 'money', group: 'balance' },
  { field: 'total_debt', labelKey: 'financials.totalDebt', kind: 'money', group: 'balance' },
  { field: 'cash', labelKey: 'financials.cash', kind: 'money', group: 'balance' },
  { field: 'inventory', labelKey: 'financials.inventory', kind: 'money', group: 'balance' },
  { field: 'receivables', labelKey: 'financials.receivables', kind: 'money', group: 'balance' },

  { field: 'operating_cash_flow', labelKey: 'financials.ocf', kind: 'money', group: 'cashflow' },
  { field: 'free_cash_flow', labelKey: 'financials.fcf', kind: 'money', group: 'cashflow' },
  { field: 'capex', labelKey: 'financials.capex', kind: 'money', group: 'cashflow' },
  { field: 'buyback', labelKey: 'financials.buyback', kind: 'money', group: 'cashflow' },
  { field: 'dividends_paid', labelKey: 'financials.dividendsPaid', kind: 'money', group: 'cashflow' },

  { field: 'revenue_yoy', labelKey: 'financials.revenueYoy', kind: 'ratio', group: 'derived' },
  { field: 'net_income_yoy', labelKey: 'financials.netIncomeYoy', kind: 'ratio', group: 'derived' },
  { field: 'gross_margin', labelKey: 'profile.grossMargin', kind: 'ratio', group: 'derived' },
  { field: 'operating_margin', labelKey: 'profile.operatingMargin', kind: 'ratio', group: 'derived' },
  { field: 'net_margin', labelKey: 'profile.netMargin', kind: 'ratio', group: 'derived' },
  { field: 'roe', labelKey: 'profile.roe', kind: 'ratio', group: 'derived' },
  { field: 'roa', labelKey: 'profile.roa', kind: 'ratio', group: 'derived' },
]

const GROUPS: { key: Item['group']; titleKey: string }[] = [
  { key: 'income', titleKey: 'financials.group.income' },
  { key: 'balance', titleKey: 'financials.group.balance' },
  { key: 'cashflow', titleKey: 'financials.group.cashflow' },
  { key: 'derived', titleKey: 'financials.group.derived' },
]

function formatValue(value: number | null | undefined, kind: Kind, currency: string): string {
  if (value === null || value === undefined) return '—'
  if (kind === 'ratio') return fmtRatioPct(value)
  if (kind === 'number') return fmtNum(value, 2)
  return fmtAmount(value, currency)
}

function periodLabel(period: string): string {
  // 后端给的是 YYYY-MM-DD；季度报表用 YYYY-MM 更清爽
  return period.length >= 7 ? period.slice(0, 7) : period
}

interface Props {
  financials: Financials | null
  currency?: string
  t: TranslateFn
}

const FinancialsCard: React.FC<Props> = ({ financials, currency = '', t }) => {
  const [mode, setMode] = useState<Mode>('annual')

  const annual = financials?.annual ?? {}
  const quarterly = financials?.quarterly ?? {}
  const periodsMap = mode === 'annual' ? annual : quarterly
  const periods = Object.keys(periodsMap).sort().reverse()

  const hasAny = Object.keys(annual).length > 0 || Object.keys(quarterly).length > 0

  const actions = hasAny ? (
    <Segmented<Mode>
      value={mode}
      onChange={setMode}
      options={[
        { value: 'annual', label: t('financials.annual') },
        { value: 'quarterly', label: t('financials.quarterly') },
      ]}
    />
  ) : null

  if (!hasAny) {
    return (
      <Card title={t('financials.title')}>
        <EmptyState text={t('financials.empty')} compact />
      </Card>
    )
  }

  const rowsFor = (group: Item['group']) => {
    const items = ITEMS.filter((item) => item.group === group)
    const visible = items.filter((item) =>
      periods.some((period) => {
        const value = (periodsMap[period] as FinancialPeriod)?.[item.field]
        return value !== null && value !== undefined
      }),
    )
    if (visible.length === 0) return null
    return (
      <>
        <tr>
          <td
            colSpan={periods.length + 1}
            className="sticky left-0 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-500"
          >
            {t(GROUPS.find((entry) => entry.key === group)!.titleKey)}
          </td>
        </tr>
        {visible.map((item) => (
          <tr key={item.field} className="border-t border-slate-50">
            <td className="sticky left-0 bg-white px-2 py-1.5 text-xs text-slate-500">
              {t(item.labelKey)}
            </td>
            {periods.map((period) => {
              const value = (periodsMap[period] as FinancialPeriod)?.[item.field]
              const isRatio = item.kind === 'ratio'
              const isYoy = item.field.endsWith('_yoy')
              return (
                <td
                  key={period}
                  className={`px-2 py-1.5 text-right text-xs tabular-nums ${
                    isRatio
                      ? isYoy
                        ? trendClass(value)
                        : 'text-slate-800'
                      : 'text-slate-800'
                  }`}
                >
                  {isRatio && isYoy
                    ? value === null || value === undefined
                      ? '—'
                      : signedPct(value * 100)
                    : formatValue(value, item.kind, currency)}
                </td>
              )
            })}
          </tr>
        ))}
      </>
    )
  }

  return (
    <Card title={t('financials.title')} actions={actions} flush>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-slate-100">
              <th className="sticky left-0 bg-white px-2 py-2 text-left text-[11px] font-medium text-slate-400">
                {t('financials.item')}
              </th>
              {periods.map((period) => (
                <th
                  key={period}
                  className="whitespace-nowrap px-2 py-2 text-right text-[11px] font-medium text-slate-400"
                >
                  {periodLabel(period)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {GROUPS.map((group) => (
              <Fragment key={group.key}>{rowsFor(group.key)}</Fragment>
            ))}
          </tbody>
        </table>
      </div>
      <p className="px-3 py-2 text-[11px] text-slate-300">{t('financials.note')}</p>
    </Card>
  )
}

export default FinancialsCard
