/**
 * 公司概况：基本信息 + 估值 / 盈利 / 成长 / 财务健康 / 股东回报五组指标 + 业务简介。
 *
 * 比率字段（利润率、ROE、增速）后端给小数，统一走 `fmtRatioPct`；
 * 金额字段走 `fmtAmount`。混用会让 0.25 显示成 "0.25%"。
 */

import { useState } from 'react'
import type { CompanyProfile } from '../api/types'
import type { TranslateFn } from '../i18n'
import { fmtAmount, fmtNum, fmtRatioPct } from '../utils/format'
import { Card, EmptyState } from './ui'

interface Props {
  profile: CompanyProfile | null
  currency?: string
  t: TranslateFn
}

const ProfileCard: React.FC<Props> = ({ profile, currency = '', t }) => {
  const [expanded, setExpanded] = useState(false)

  if (!profile) {
    return (
      <Card title={t('profile.title')}>
        <EmptyState text={t('common.empty')} compact />
      </Card>
    )
  }

  const groups: { titleKey: string; rows: { labelKey: string; value: string }[] }[] = [
    {
      titleKey: 'profile.valuation',
      rows: [
        { labelKey: 'profile.pe', value: fmtNum(profile.pe_trailing, 2) },
        { labelKey: 'profile.peForward', value: fmtNum(profile.pe_forward, 2) },
        { labelKey: 'profile.pb', value: fmtNum(profile.pb, 2) },
        { labelKey: 'profile.ps', value: fmtNum(profile.ps, 2) },
        { labelKey: 'profile.peg', value: fmtNum(profile.peg_ratio, 2) },
        { labelKey: 'profile.evEbitda', value: fmtNum(profile.ev_to_ebitda, 2) },
      ],
    },
    {
      titleKey: 'profile.profitability',
      rows: [
        { labelKey: 'profile.grossMargin', value: fmtRatioPct(profile.gross_margin) },
        { labelKey: 'profile.operatingMargin', value: fmtRatioPct(profile.operating_margin) },
        { labelKey: 'profile.netMargin', value: fmtRatioPct(profile.profit_margin) },
        { labelKey: 'profile.roe', value: fmtRatioPct(profile.roe) },
        { labelKey: 'profile.roa', value: fmtRatioPct(profile.roa) },
        { labelKey: 'profile.fcf', value: fmtAmount(profile.free_cashflow, currency) },
      ],
    },
    {
      titleKey: 'profile.growth',
      rows: [
        { labelKey: 'profile.revenueGrowth', value: fmtRatioPct(profile.revenue_growth) },
        { labelKey: 'profile.earningsGrowth', value: fmtRatioPct(profile.earnings_growth) },
        { labelKey: 'profile.beta', value: fmtNum(profile.beta, 2) },
        { labelKey: 'profile.shortFloat', value: fmtRatioPct(profile.short_pct_of_float) },
      ],
    },
    {
      titleKey: 'profile.health',
      rows: [
        { labelKey: 'profile.debtToEquity', value: fmtNum(profile.debt_to_equity, 2) },
        { labelKey: 'profile.currentRatio', value: fmtNum(profile.current_ratio, 2) },
        { labelKey: 'profile.quickRatio', value: fmtNum(profile.quick_ratio, 2) },
        { labelKey: 'financials.totalDebt', value: fmtAmount(profile.total_debt, currency) },
        { labelKey: 'financials.cash', value: fmtAmount(profile.total_cash, currency) },
      ],
    },
    {
      titleKey: 'profile.dividend',
      rows: [
        { labelKey: 'profile.dividendYield', value: fmtRatioPct(profile.dividend_yield) },
        { labelKey: 'profile.payoutRatio', value: fmtRatioPct(profile.payout_ratio) },
        { labelKey: 'profile.insiders', value: fmtRatioPct(profile.held_by_insiders) },
        { labelKey: 'profile.institutions', value: fmtRatioPct(profile.held_by_institutions) },
      ],
    },
  ]

  const basics = [
    profile.sector ? `${t('profile.sector')}: ${profile.sector}` : null,
    profile.industry ? `${t('profile.industry')}: ${profile.industry}` : null,
    profile.country ? `${t('profile.country')}: ${profile.country}` : null,
    profile.employees
      ? `${t('profile.employees')}: ${profile.employees.toLocaleString()}`
      : null,
  ].filter(Boolean) as string[]

  const summary = profile.summary ?? ''
  const longSummary = summary.length > 320

  return (
    <Card
      title={t('profile.title')}
      actions={
        profile.website ? (
          <a
            href={profile.website}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[11px] text-blue-600 hover:underline"
          >
            {t('profile.website')} ↗
          </a>
        ) : undefined
      }
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
        {basics.length > 0 ? (
          basics.map((text) => <span key={text}>{text}</span>)
        ) : (
          <span className="text-slate-300">{t('common.empty')}</span>
        )}
        {profile.market_cap ? (
          <span>
            {t('quote.marketCap')}: {fmtAmount(profile.market_cap, currency)}
          </span>
        ) : null}
        {profile.enterprise_value ? (
          <span>EV: {fmtAmount(profile.enterprise_value, currency)}</span>
        ) : null}
      </div>

      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
        {groups.map((group) => (
          <div key={group.titleKey}>
            <div className="mb-1.5 text-[11px] font-medium text-slate-400">
              {t(group.titleKey)}
            </div>
            <div className="space-y-0.5">
              {group.rows.map((row) => (
                <div
                  key={row.labelKey}
                  className="flex items-baseline justify-between gap-2 leading-relaxed"
                >
                  <span className="truncate text-[11px] text-slate-400">{t(row.labelKey)}</span>
                  <span className="shrink-0 text-xs tabular-nums text-slate-800">{row.value}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {summary ? (
        <div className="mt-4 border-t border-slate-100 pt-3">
          <div className="mb-1 text-[11px] font-medium text-slate-400">{t('profile.business')}</div>
          <p className="text-xs leading-relaxed text-slate-600">
            {longSummary && !expanded ? `${summary.slice(0, 320)}…` : summary}
          </p>
          {longSummary ? (
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="mt-1 text-[11px] text-blue-600 hover:underline"
            >
              {expanded ? t('common.collapse') : t('common.expand')}
            </button>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}

export default ProfileCard
