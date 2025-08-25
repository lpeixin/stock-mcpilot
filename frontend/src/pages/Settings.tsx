import React, { useEffect, useState } from 'react'
import { useSettings } from '../store/useSettings'
import { setLang, t } from '../i18n'

const Settings: React.FC = () => {
  const { init, mode, api_key, local_model, language, save } = useSettings(); setLang(language as any)
  const [form, setForm] = useState({ mode, api_key, local_model, language })
  useEffect(() => { init() }, [init])
  useEffect(() => { setForm({ mode, api_key, local_model, language }) }, [mode, api_key, local_model, language])
  const update = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))
  const submit = async () => { await save(form) }
  return (
    <div className="max-w-lg space-y-4">
      <div>
        <label className="block text-sm font-medium mb-1">{t('settings.mode')}</label>
        <select value={form.mode} onChange={e=>update('mode', e.target.value)} className="border rounded px-3 py-2 w-full">
          <option value="local">{t('settings.mode.local')}</option>
          <option value="cloud">{t('settings.mode.cloud')}</option>
        </select>
      </div>
      <div>
        <label className="block text-sm font-medium mb-1">{t('settings.language')}</label>
        <select value={form.language} onChange={e=>update('language', e.target.value)} className="border rounded px-3 py-2 w-full">
          <option value="en">English</option>
          <option value="zh">中文</option>
        </select>
      </div>
      {form.mode === 'cloud' && (
        <div>
          <label className="block text-sm font-medium mb-1">{t('settings.api_key')}</label>
          <input value={form.api_key || ''} onChange={e=>update('api_key', e.target.value)} className="border rounded px-3 py-2 w-full" placeholder={t('settings.api_key')} />
        </div>
      )}
      {form.mode === 'local' && (
        <div>
          <label className="block text-sm font-medium mb-1">{t('settings.local_model')}</label>
            <input value={form.local_model || ''} onChange={e=>update('local_model', e.target.value)} className="border rounded px-3 py-2 w-full" placeholder="llama3" />
        </div>
      )}
      <button onClick={submit} className="bg-blue-600 text-white rounded px-4 py-2 text-sm">{t('settings.save')}</button>
    </div>
  )
}
export default Settings
