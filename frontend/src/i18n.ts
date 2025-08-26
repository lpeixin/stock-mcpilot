// Simple i18n utility
export type Lang = 'en' | 'zh'

const dict: Record<Lang, Record<string, string>> = {
  en: {
    'search.placeholder': 'Ticker',
    'search.market.us': 'US',
    'search.market.hk': 'HK',
    'search.market.cn': 'CN',
    'search.action': 'Search',
    'analysis.ask.placeholder': 'Ask model (optional)',
    'analysis.action': 'Analyze',
    'loading': 'Loading...',
    'empty.prompt': 'Enter a ticker to search.',
    'summary.title': 'Statistical Summary',
    'summary.range': 'Range',
    'metric.count': 'Days',
    'metric.count.hint': 'Trading days',
    'metric.mean_close': 'Mean Close',
    'metric.vol_mean': 'Mean Volume',
    'metric.return_pct': 'Return',
    'metric.return_pct.hint': 'Latest / First - 1',
    'metric.max_drawdown_pct': 'Max Drawdown',
    'metric.max_drawdown_pct.hint': 'Peak to trough',
    'metric.volatility_pct': 'Volatility',
    'metric.volatility_pct.hint': 'Std of daily returns',
    'analysis.title': 'Model Analysis',
    'settings.mode': 'Mode',
    'settings.mode.local': 'Local',
    'settings.mode.cloud': 'Cloud',
    'settings.api_key': 'API Key',
    'settings.local_model': 'Local Model Name',
    'settings.language': 'Language',
    'settings.save': 'Save'
  , 'nav.home': 'Home'
  , 'nav.settings': 'Settings'
  , 'footer.disclaimer': 'Beta Scaffold - Not investment advice'
  , 'chart.close': 'Close Price'
  , 'label.date': 'Date'
  , 'search.empty': 'Ticker is required'
  },
  zh: {
    'search.placeholder': '股票代码',
    'search.market.us': '美股',
    'search.market.hk': '港股',
    'search.market.cn': 'A股',
    'search.action': '查询',
    'analysis.ask.placeholder': '向模型提问 (可选)',
    'analysis.action': '分析',
    'loading': '加载中...',
    'empty.prompt': '请输入股票代码查询。',
    'summary.title': '基础统计摘要',
    'summary.range': '区间',
    'metric.count': '样本天数',
    'metric.count.hint': '交易日数量',
    'metric.mean_close': '均价',
    'metric.vol_mean': '均量',
    'metric.return_pct': '区间收益',
    'metric.return_pct.hint': '最新价 / 起始价 - 1',
    'metric.max_drawdown_pct': '最大回撤',
    'metric.max_drawdown_pct.hint': '峰值至谷底最大跌幅',
    'metric.volatility_pct': '波动率',
    'metric.volatility_pct.hint': '日收益标准差',
    'analysis.title': '模型分析',
    'settings.mode': '模型模式',
    'settings.mode.local': '本地',
    'settings.mode.cloud': '云端',
    'settings.api_key': 'API Key',
    'settings.local_model': '本地模型名称',
    'settings.language': '界面语言',
    'settings.save': '保存'
  , 'nav.home': '主页'
  , 'nav.settings': '设置'
  , 'footer.disclaimer': 'Beta Scaffold - 不构成投资建议'
  , 'chart.close': '收盘价走势'
  , 'label.date': '日期'
  , 'search.empty': '请输入股票代码'
  }
}

let current: Lang = 'en'
export function setLang(l: Lang){ current = l }
export function t(key: string){ return dict[current][key] || key }
export function getCurrentLang(){ return current }
