import { useEffect, useState } from 'react'
import { Link, Outlet, useLocation } from 'react-router-dom'

const navItems = [
  { path: '/', label: 'Upload', icon: '📤' },
  { path: '/files', label: 'Arquivos', icon: '📁' },
  { path: '/rules', label: 'Regras', icon: '📋' },
]

export default function Layout() {
  const location = useLocation()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [apiHealth, setApiHealth] = useState<'loading' | { version: string } | 'offline'>('loading')

  useEffect(() => {
    fetch('/api/health')
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((d: { status?: string; version?: string }) =>
        setApiHealth({ version: typeof d.version === 'string' ? d.version : '?' }),
      )
      .catch(() => setApiHealth('offline'))
  }, [])

  return (
    <div className="min-h-screen flex">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-30 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <nav className={`
        fixed md:static inset-y-0 left-0 z-40
        w-56 bg-gray-800 text-white p-4 flex flex-col gap-1
        transform transition-transform duration-200 ease-in-out
        ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}
        md:translate-x-0
      `}>
        <div className="flex items-center justify-between mb-6 px-3">
          <h1 className="text-lg font-bold">SPED Audit</h1>
          <button
            onClick={() => setSidebarOpen(false)}
            className="md:hidden text-gray-400 hover:text-white text-xl"
            aria-label="Fechar menu"
          >
            ✕
          </button>
        </div>
        {navItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            onClick={() => setSidebarOpen(false)}
            className={`px-3 py-2 rounded text-sm ${
              location.pathname === item.path ? 'bg-gray-600' : 'hover:bg-gray-700'
            }`}
          >
            {item.icon} {item.label}
          </Link>
        ))}
      </nav>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile header with hamburger */}
        <div className="md:hidden bg-gray-800 text-white px-4 py-3 flex items-center gap-3">
          <button
            onClick={() => setSidebarOpen(true)}
            className="text-xl"
            aria-label="Abrir menu"
          >
            ☰
          </button>
          <span className="font-bold text-sm">SPED Audit</span>
        </div>

        <main className="flex-1 p-4 md:p-6 overflow-auto">
          <Outlet />
        </main>

        <footer className="shrink-0 border-t border-gray-200 bg-gray-50/80 px-4 py-2 text-[11px] text-gray-500 md:px-6">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              Interface <span className="font-mono text-gray-600">v{__APP_VERSION__}</span>
            </span>
            {apiHealth === 'loading' && <span className="text-gray-400">· API…</span>}
            {apiHealth === 'offline' && (
              <span className="text-amber-700">
                · API offline — confira se o backend está no ar e o proxy <code className="rounded bg-gray-200 px-0.5">/api</code>
              </span>
            )}
            {apiHealth !== 'loading' && apiHealth !== 'offline' && (
              <span>
                · API <span className="font-mono text-gray-600">v{apiHealth.version}</span>
              </span>
            )}
            <span className="hidden sm:inline text-gray-400">
              · Chave: <code className="rounded bg-gray-200 px-1 text-gray-600">VITE_API_KEY</code> no{' '}
              <code className="rounded bg-gray-200 px-1">frontend/.env.local</code> ={' '}
              <code className="rounded bg-gray-200 px-1">API_KEY</code> do backend
            </span>
          </div>
        </footer>
      </div>
    </div>
  )
}
