import React, { useEffect, useState } from 'react'
import { useSettings } from '../store/useSettings'

const Settings: React.FC = () => {
  const { init, mode, api_key, local_model, save } = useSettings()
  const [form, setForm] = useState({ mode, api_key, local_model })
  useEffect(() => { init() }, [init])
  useEffect(() => { setForm({ mode, api_key, local_model }) }, [mode, api_key, local_model])
  const update = (k: string, v: any) => setForm(f => ({ ...f, [k]: v }))
  const submit = async () => { await save(form) }
  return (
    <div className="max-w-lg space-y-4">
      <div>
        <label className="block text-sm font-medium mb-1">模型模式</label>
        <select value={form.mode} onChange={e=>update('mode', e.target.value)} className="border rounded px-3 py-2 w-full">
          <option value="local">本地</option>
          <option value="cloud">云端</option>
        </select>
      </div>
      {form.mode === 'cloud' && (
        <div>
          <label className="block text-sm font-medium mb-1">API Key</label>
          <input value={form.api_key || ''} onChange={e=>update('api_key', e.target.value)} className="border rounded px-3 py-2 w-full" placeholder="输入云端模型 API Key" />
        </div>
      )}
      {form.mode === 'local' && (
        <div>
          <label className="block text-sm font-medium mb-1">本地模型名称</label>
            <input value={form.local_model || ''} onChange={e=>update('local_model', e.target.value)} className="border rounded px-3 py-2 w-full" placeholder="llama3" />
        </div>
      )}
      <button onClick={submit} className="bg-blue-600 text-white rounded px-4 py-2 text-sm">保存</button>
    </div>
  )
}
export default Settings
