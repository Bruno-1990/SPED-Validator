import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import UploadPage from './pages/UploadPage'
import FilesPage from './pages/FilesPage'
import FileDetailPage from './pages/FileDetailPage'
import RulesPage from './pages/RulesPage'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<UploadPage />} />
          <Route path="/files" element={<FilesPage />} />
          <Route path="/files/:fileId" element={<FileDetailPage />} />
          <Route path="/rules" element={<RulesPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
)
