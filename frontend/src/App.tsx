import React, { useState } from 'react'
import Home from './pages/Home'
import Settings from './pages/Settings'

const App: React.FC = () => {
  const [page, setPage] = useState<'home' | 'settings'>('home')
  return (
    <div className="min-h-screen flex flex-col">
      <header className="p-4 shadow bg-white flex items-center justify-between">
        <h1 className="font-semibold text-lg">Stock MCPilot</h1>
        <nav className="space-x-4 text-sm">
          <button onClick={() => setPage('home')} className={page==='home' ? 'text-blue-600 font-medium' : 'text-gray-600'}>主页</button>
          <button onClick={() => setPage('settings')} className={page==='settings' ? 'text-blue-600 font-medium' : 'text-gray-600'}>设置</button>
        </nav>
      </header>
      <main className="flex-1 max-w-5xl w-full mx-auto p-6">
        {page === 'home' ? <Home /> : <Settings />}
      </main>
      <footer className="text-center text-xs text-gray-400 py-4">Beta Scaffold - 不构成投资建议</footer>
    </div>
  )
}
export default App
