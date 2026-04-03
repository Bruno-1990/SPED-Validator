import { Link, Outlet, useLocation } from 'react-router-dom'

const navItems = [
  { path: '/', label: 'Upload', icon: '📤' },
  { path: '/files', label: 'Arquivos', icon: '📁' },
]

export default function Layout() {
  const location = useLocation()

  return (
    <div className="min-h-screen flex">
      <nav className="w-56 bg-gray-800 text-white p-4 flex flex-col gap-1">
        <h1 className="text-lg font-bold mb-6 px-3">SPED Audit</h1>
        {navItems.map((item) => (
          <Link
            key={item.path}
            to={item.path}
            className={`px-3 py-2 rounded text-sm ${
              location.pathname === item.path ? 'bg-gray-600' : 'hover:bg-gray-700'
            }`}
          >
            {item.icon} {item.label}
          </Link>
        ))}
      </nav>
      <main className="flex-1 p-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
