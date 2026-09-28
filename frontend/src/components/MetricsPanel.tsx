/**
 * 区间统计面板。
 *
 * 全部是回溯统计量，不含预测。红涨绿跌同样走 `trendClass`。
 */

import type { PriceSummary } from '../api/types'
import type { TranslateFn } from '../i18n'
import { signedPct, trendClass } from '../theme'
import { fmtNum, fmtPct, fmtPrice, fmtVolume } from '../utils/format'
import { Card, EmptyState, Stat, StatGrid } from './ui'

interface Props {
  summary: PriceSummary | null
  t: TranslateFn
}

const MetricsPanel: React.FC<Props> = ({ summary, t }) => {
  if (!summary) {
    return (
      <Card title={t('metrics.title')}>
        <EmptyState text={t('common.empty')} compact />
      </Card>
    )
  }

  const range =
    summary.start_date && summary.end_date
      ? `${summary.start_date} ~ ${summary.end_date}`
      : undefined

  return (
    <Card title={t('metrics.title')} subtitle={range}>
      <StatGrid columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-5">
        <Stat
          label={t('metrics.return')}
          value={signedPct(summary.return_pct)}
          valueClass={trendClass(summary.return_pct)}
        />
        <Stat
          label={t('metrics.drawdown')}
          value={fmtPct(summary.max_drawdown_pct)}
          valueClass="text-[#1f9d63]"
        />
        <Stat label={t('metrics.volatility')} value={fmtPct(summary.volatility_pct)} />
        <Stat label={t('metrics.annVolatility')} value={fmtPct(summary.annualized_volatility_pct)} />
        <Stat
          label={t('metrics.days')}
          value={fmtNum(summary.count, 0)}
          hint={
            summary.up_days !== null && summary.up_days !== undefined
              ? `${t('metrics.upDown')} ${summary.up_days} / ${summary.down_days ?? 0}`
              : undefined
          }
        />
        <Stat
          label={t('metrics.bestDay')}
          value={signedPct(summary.max_single_day_gain_pct)}
          valueClass={trendClass(summary.max_single_day_gain_pct)}
        />
        <Stat
          label={t('metrics.worstDay')}
          value={fmtPct(summary.max_single_day_loss_pct)}
          valueClass="text-[#1f9d63]"
        />
        <Stat
          label={t('metrics.momentum')}
          value={signedPct(summary.momentum_acceleration_pct)}
          valueClass={trendClass(summary.momentum_acceleration_pct)}
          hint={
            summary.recent_20d_return_pct !== null && summary.recent_20d_return_pct !== undefined
              ? `20D ${signedPct(summary.recent_20d_return_pct)}`
              : undefined
          }
        />
        <Stat label={t('metrics.high')} value={fmtPrice(summary.high)} />
        <Stat label={t('metrics.low')} value={fmtPrice(summary.low)} />
        <Stat label={t('metrics.mean')} value={fmtPrice(summary.mean_close)} />
        <Stat
          label={t('metrics.volLast')}
          value={fmtVolume(summary.vol_last)}
          hint={
            summary.vol_mean !== null && summary.vol_mean !== undefined
              ? `${t('metrics.volMean')} ${fmtVolume(summary.vol_mean)}`
              : undefined
          }
        />
      </StatGrid>
    </Card>
  )
}

export default MetricsPanel
