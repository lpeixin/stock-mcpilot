/**
 * 设置页：模型服务 + 分析上下文 + 界面 + 安全说明。
 *
 * 几个刻意的设计：
 *   - **草稿态**：改动先落在本地 draft，点「保存」才落盘。用户可以放心试参数，
 *     「测试连接」也是拿 draft 去测，不必先保存再测。
 *   - **密钥掩码**：输入框里显示的是 `sk-1****cdef`。用户不动它，保存时后端
 *     识别出掩码就保留原值；用户改了，才当成新密钥写入。
 *   - **环境变量锁**：被 env 覆盖的字段会标出来并禁用输入，否则用户改了没生效
 *     却查不出原因。
 */

import { useEffect, useMemo, useState } from 'react'
import { fetchModels, testConnection } from '../api'
import type { AnalysisConfig, AppConfig, LLMConfig, TestResult } from '../api/types'
import { describeError } from '../api/client'
import {
  Badge,
  Button,
  Card,
  Field,
  Segmented,
  Spinner,
  Toggle,
  inputClass,
} from '../components/ui'
import { makeTranslator } from '../i18n'
import type { Lang } from '../i18n'
import { useApp } from '../store/useApp'
import { useConfig } from '../store/useConfig'
import { fmtNum } from '../utils/format'

const SECTION_ORDER = [
  'quote',
  'indicators',
  'summary',
  'candles',
  'profile',
  'financials',
  'earnings',
  'analyst',
  'news',
]

const SECTION_KEY: Record<string, string> = {
  quote: 'analysis.section.quote',
  indicators: 'analysis.section.indicators',
  summary: 'analysis.section.summary',
  candles: 'analysis.section.candles',
  profile: 'analysis.section.profile',
  financials: 'analysis.section.financials',
  earnings: 'analysis.section.earnings',
  analyst: 'analysis.section.analyst',
  news: 'analysis.section.news',
}

function sameJson(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

const Settings: React.FC = () => {
  const { language, setLanguage } = useApp()
  const t = useMemo(() => makeTranslator(language), [language])
  const { config, loading: configLoading, error: configError, load, save } = useConfig()

  const [llm, setLlm] = useState<LLMConfig | null>(null)
  const [analysis, setAnalysis] = useState<AnalysisConfig | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [fetchingModels, setFetchingModels] = useState(false)
  const [modelMessage, setModelMessage] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<TestResult | null>(null)
  const [testError, setTestError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [keyCleared, setKeyCleared] = useState(false)

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!config) return
    setLlm(config.llm)
    setAnalysis(config.analysis)
    setKeyCleared(false)
  }, [config])

  const locked = config?.locked_by_env ?? []
  const presets = config?.presets ?? {}
  const preset = llm ? presets[llm.preset] : undefined

  // 服务商按分组渲染：远程服务商在前，本地模型在最后。
  // 分组顺序由服务端下发（config.preset_groups），前端不硬编码 —— 但要有兜底，
  // 否则连老后端时整块服务商列表会凭空消失。
  const groupedPresets = useMemo(() => {
    const order =
      config?.preset_groups && config.preset_groups.length > 0
        ? config.preset_groups
        : [
            { key: 'remote', label: '远程 / 自建服务' },
            { key: 'local', label: '本地模型' },
          ]
    const entries = Object.entries(presets)
    const groupOf = (item: { group?: string }) => item.group ?? 'remote'
    const known = new Set(order.map((item) => item.key))

    const groups = order.map((item) => ({
      key: item.key,
      label: item.label,
      items: entries.filter(([, value]) => groupOf(value) === item.key),
    }))
    // 出现了服务端没声明的分组时，单独兜一个"其他"，不要静默丢掉。
    const orphans = entries.filter(([, value]) => !known.has(groupOf(value)))
    if (orphans.length > 0) {
      groups.push({ key: 'other', label: '其他', items: orphans })
    }
    return groups.filter((item) => item.items.length > 0)
  }, [config, presets])

  const groupLabel = (key: string, fallback: string) => {
    const translated = t(`settings.provider.group.${key}`)
    // t() 对缺失键会原样返回 key，这里用它来判断是否需要回退到服务端文案。
    return translated === `settings.provider.group.${key}` ? fallback : translated
  }

  const dirty =
    config !== null &&
    llm !== null &&
    analysis !== null &&
    (!sameJson(llm, config.llm) || !sameJson(analysis, config.analysis))

  const patchLlm = (patch: Partial<LLMConfig>) =>
    setLlm((current) => (current ? { ...current, ...patch } : current))

  const patchAnalysis = (patch: Partial<AnalysisConfig>) =>
    setAnalysis((current) => (current ? { ...current, ...patch } : current))

  const choosePreset = (name: string) => {
    const next = presets[name]
    if (!next) return
    setLlm((current) =>
      current
        ? {
            ...current,
            preset: name,
            kind: next.kind,
            base_url: next.base_url,
            // 模型名沿用预设默认值；用户填过的自定义模型不覆盖
            model: next.default_model || current.model,
          }
        : current,
    )
    setModels([])
    setModelMessage(null)
    setTestResult(null)
    setTestError(null)
  }

  const overridePayload = llm
    ? {
        preset: llm.preset,
        kind: llm.kind,
        base_url: llm.base_url,
        api_key: llm.api_key,
        model: llm.model,
        temperature: llm.temperature,
        max_tokens: llm.max_tokens,
        timeout: llm.timeout,
      }
    : undefined

  const handleFetchModels = async () => {
    if (!overridePayload) return
    setFetchingModels(true)
    setModelMessage(null)
    try {
      const result = await fetchModels(overridePayload)
      setModels(result.models)
      setModelMessage(result.message ?? null)
    } catch (caught) {
      setModels([])
      setModelMessage(describeError(caught))
    } finally {
      setFetchingModels(false)
    }
  }

  const handleTest = async () => {
    if (!overridePayload) return
    setTesting(true)
    setTestResult(null)
    setTestError(null)
    try {
      const result = await testConnection(overridePayload, true)
      setTestResult(result)
    } catch (caught) {
      setTestError(describeError(caught))
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async () => {
    if (!llm || !analysis) return
    setSaving(true)
    await save({
      llm,
      analysis: { ...analysis, language },
      ui: { language },
    })
    setSaving(false)
    setSavedAt(Date.now())
  }

  const handleLanguage = (next: Lang) => {
    setLanguage(next)
    patchAnalysis({ language: next })
  }

  useEffect(() => {
    if (savedAt === null) return
    const timer = setTimeout(() => setSavedAt(null), 2200)
    return () => clearTimeout(timer)
  }, [savedAt])

  if (!llm || !analysis) {
    return (
      <Card title={t('settings.title')}>
        <div className="flex items-center gap-2 py-8 text-xs text-slate-400">
          {configLoading ? <Spinner className="h-3.5 w-3.5" /> : null}
          {configError ?? t('common.loading')}
        </div>
      </Card>
    )
  }

  const isLocked = (path: string) => locked.includes(path)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-base font-semibold text-slate-900">{t('settings.title')}</h1>
        <div className="flex items-center gap-2">
          {savedAt !== null ? (
            <span className="text-[11px] text-emerald-600">{t('common.saved')}</span>
          ) : null}
          {dirty ? (
            <span className="text-[11px] text-amber-600">{t('settings.unsaved')}</span>
          ) : null}
          <Button variant="primary" onClick={() => void handleSave()} disabled={saving || !dirty}>
            {saving ? <Spinner className="h-3 w-3" /> : null}
            {saving ? t('common.saving') : t('common.save')}
          </Button>
        </div>
      </div>

      {locked.length > 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <p className="text-xs text-amber-800">{t('settings.lockedByEnv')}</p>
          <p className="mt-1 font-mono text-[11px] text-amber-700">{locked.join(', ')}</p>
        </div>
      ) : null}

      {/* ---------------------------------------------------------- 模型服务 */}
      <Card title={t('settings.section.model')} subtitle={t('settings.provider.hint')}>
        <div className="space-y-4">
          <div>
            <div className="mb-1.5 text-xs font-medium text-slate-600">
              {t('settings.provider')}
            </div>
            <div className="space-y-3" data-provider-groups>
              {groupedPresets.map((group) => (
                <div key={group.key} data-provider-group={group.key}>
                  <div className="mb-1 text-[11px] font-medium text-slate-400">
                    {groupLabel(group.key, group.label)}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {group.items.map(([name, item]) => (
                      <button
                        key={name}
                        type="button"
                        data-preset={name}
                        onClick={() => choosePreset(name)}
                        className={`rounded-lg border px-2.5 py-1.5 text-xs transition ${
                          llm.preset === name
                            ? 'border-blue-400 bg-blue-50 text-blue-700'
                            : 'border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            {preset?.hint ? (
              <p className="mt-2 text-[11px] leading-relaxed text-slate-400">{preset.hint}</p>
            ) : null}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label={t('settings.baseUrl')}
              hint={isLocked('llm.base_url') ? t('settings.locked') : t('settings.baseUrl.hint')}
            >
              <input
                className={inputClass}
                value={llm.base_url}
                disabled={isLocked('llm.base_url')}
                onChange={(event) => patchLlm({ base_url: event.target.value })}
                spellCheck={false}
              />
            </Field>

            <Field
              label={t('settings.apiKey')}
              hint={
                isLocked('llm.api_key')
                  ? t('settings.locked')
                  : t('settings.apiKey.hint', { path: config?.config_path ?? '' })
              }
            >
              <div className="flex items-center gap-2">
                <input
                  className={inputClass}
                  type="password"
                  value={keyCleared ? '' : llm.api_key}
                  disabled={isLocked('llm.api_key')}
                  placeholder={
                    preset?.requires_key
                      ? t('settings.apiKey.placeholder')
                      : t('settings.apiKey.optional')
                  }
                  onChange={(event) => {
                    setKeyCleared(false)
                    patchLlm({ api_key: event.target.value })
                  }}
                  spellCheck={false}
                  autoComplete="off"
                />
                {llm.api_key_set && !keyCleared ? (
                  <button
                    type="button"
                    onClick={() => {
                      setKeyCleared(true)
                      patchLlm({ api_key: '', api_key_set: false })
                    }}
                    disabled={isLocked('llm.api_key')}
                    className="shrink-0 rounded border border-slate-200 px-2 py-1.5 text-[11px] text-slate-500 transition hover:bg-slate-50 disabled:opacity-40"
                  >
                    {t('settings.apiKey.clear')}
                  </button>
                ) : null}
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                {llm.api_key_set && !keyCleared
                  ? t('settings.apiKey.set', { mask: llm.api_key })
                  : t('settings.apiKey.notSet')}
              </p>
            </Field>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label={t('settings.model')}
              hint={
                isLocked('llm.model')
                  ? t('settings.locked')
                  : modelMessage ?? t('settings.model.hint')
              }
            >
              <div className="flex items-center gap-2">
                <input
                  className={inputClass}
                  list="smp-model-options"
                  value={llm.model}
                  disabled={isLocked('llm.model')}
                  onChange={(event) => patchLlm({ model: event.target.value })}
                  placeholder={preset?.default_model || t('settings.model.manual')}
                  spellCheck={false}
                  autoComplete="off"
                />
                <datalist id="smp-model-options">
                  {models.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
                <Button
                  size="sm"
                  onClick={() => void handleFetchModels()}
                  disabled={fetchingModels}
                  className="shrink-0"
                >
                  {fetchingModels ? <Spinner className="h-3 w-3" /> : null}
                  {fetchingModels ? t('settings.model.fetching') : t('settings.model.fetch')}
                </Button>
              </div>
            </Field>

            <div className="grid grid-cols-3 gap-3">
              <Field label={t('settings.temperature')} hint={t('settings.temperature.hint')}>
                <input
                  className={inputClass}
                  type="number"
                  min={0}
                  max={2}
                  step={0.1}
                  value={llm.temperature}
                  onChange={(event) => patchLlm({ temperature: Number(event.target.value) })}
                />
              </Field>
              <Field label={t('settings.maxTokens')} hint={t('settings.maxTokens.hint')}>
                <input
                  className={inputClass}
                  type="number"
                  min={16}
                  step={128}
                  value={llm.max_tokens}
                  onChange={(event) => patchLlm({ max_tokens: Number(event.target.value) })}
                />
              </Field>
              <Field label={t('settings.timeout')}>
                <input
                  className={inputClass}
                  type="number"
                  min={5}
                  step={10}
                  value={llm.timeout}
                  onChange={(event) => patchLlm({ timeout: Number(event.target.value) })}
                />
              </Field>
            </div>
          </div>

          <Field label={t('settings.systemPrompt')} hint={t('settings.systemPrompt.hint')}>
            <textarea
              className={`${inputClass} resize-y leading-relaxed`}
              rows={3}
              value={llm.system_prompt}
              onChange={(event) => patchLlm({ system_prompt: event.target.value })}
              placeholder={t('settings.systemPrompt.placeholder')}
            />
          </Field>

          <div className="flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
            <Button variant="primary" onClick={() => void handleTest()} disabled={testing}>
              {testing ? <Spinner className="h-3 w-3" /> : null}
              {testing ? t('common.testing') : t('common.test')}
            </Button>
            <span className="text-[11px] text-slate-400">{t('settings.test.hint')}</span>
          </div>

          {testError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
              {testError}
            </div>
          ) : null}

          {testResult ? (
            <div
              className={`rounded-lg border px-3 py-2.5 ${
                testResult.ok
                  ? 'border-emerald-200 bg-emerald-50'
                  : 'border-red-200 bg-red-50'
              }`}
            >
              <div className="flex items-center gap-2">
                <Badge tone={testResult.ok ? 'down' : 'up'}>
                  {testResult.ok ? t('settings.test.ok') : t('settings.test.fail')}
                </Badge>
                <span
                  className={`text-xs ${testResult.ok ? 'text-emerald-800' : 'text-red-700'}`}
                >
                  {testResult.message}
                </span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate-600 sm:grid-cols-4">
                {testResult.probe ? (
                  <>
                    <span>
                      {t('settings.test.latency')}: {fmtNum(testResult.probe.latency_ms, 0)} ms
                    </span>
                    <span>
                      {t('settings.test.models')}: {testResult.probe.models.length}
                    </span>
                    <span>
                      {t('settings.test.modelReady')}:{' '}
                      {testResult.probe.model_ready ? '✓' : '—'}
                    </span>
                  </>
                ) : null}
                {testResult.generation ? (
                  <span>
                    {t('settings.test.generation')}:{' '}
                    {testResult.generation.ok
                      ? `${fmtNum(testResult.generation.latency_ms, 0)} ms`
                      : '✗'}
                  </span>
                ) : null}
              </div>
              {testResult.generation?.sample ? (
                <p className="mt-2 rounded bg-white/70 px-2 py-1 font-mono text-[11px] text-slate-600">
                  {testResult.generation.sample}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </Card>

      {/* -------------------------------------------------------- 分析上下文 */}
      <Card title={t('settings.section.analysis')} subtitle={t('settings.analysis.desc')}>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {SECTION_ORDER.map((name) => (
              <Toggle
                key={name}
                checked={analysis.include?.[name] !== false}
                onChange={(checked) =>
                  patchAnalysis({ include: { ...analysis.include, [name]: checked } })
                }
                label={t(SECTION_KEY[name] ?? name)}
              />
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label={t('settings.analysis.newsLimit')}>
              <input
                className={inputClass}
                type="number"
                min={0}
                max={30}
                value={analysis.news_limit}
                onChange={(event) => patchAnalysis({ news_limit: Number(event.target.value) })}
              />
            </Field>
            <Field label={t('settings.analysis.candleDays')}>
              <input
                className={inputClass}
                type="number"
                min={20}
                max={1000}
                step={10}
                value={analysis.candle_days}
                onChange={(event) => patchAnalysis({ candle_days: Number(event.target.value) })}
              />
            </Field>
            <Field label={t('settings.analysis.budget')} hint={t('settings.analysis.budgetHint')}>
              <input
                className={inputClass}
                type="number"
                min={2000}
                step={1000}
                value={analysis.max_context_chars}
                onChange={(event) =>
                  patchAnalysis({ max_context_chars: Number(event.target.value) })
                }
              />
            </Field>
          </div>
        </div>
      </Card>

      {/* ---------------------------------------------------------------- 界面 */}
      <Card title={t('settings.section.ui')}>
        <Field label={t('settings.language')} className="max-w-xs">
          <Segmented<Lang>
            value={language}
            onChange={handleLanguage}
            options={[
              { value: 'zh', label: '简体中文' },
              { value: 'en', label: 'English' },
            ]}
          />
        </Field>
      </Card>

      {/* ------------------------------------------------------------ 安全存储 */}
      <Card title={t('settings.section.security')}>
        <p className="text-xs leading-relaxed text-slate-500">{t('settings.security.desc')}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div>
            <div className="text-[11px] text-slate-400">{t('settings.configPath')}</div>
            <div className="mt-0.5 break-all font-mono text-[11px] text-slate-700">
              {config?.config_path ?? '—'}
            </div>
          </div>
          <div>
            <div className="text-[11px] text-slate-400">{t('settings.apiKey')}</div>
            <div className="mt-0.5 font-mono text-[11px] text-slate-700">
              {llm.api_key_set && !keyCleared ? llm.api_key : t('settings.apiKey.notSet')}
            </div>
          </div>
        </div>
        <ul className="mt-3 space-y-1 text-[11px] leading-relaxed text-slate-400">
          <li>· {t('settings.security.point.binding')}</li>
          <li>· {t('settings.security.point.mask')}</li>
          <li>· {t('settings.security.point.permission')}</li>
        </ul>
      </Card>
    </div>
  )
}

export default Settings
