import React from 'react'
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Chantiers from './pages/Chantiers'
import Factures from './pages/Factures'
import Alertes from './pages/Alertes'

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chantiers" element={<Chantiers />} />
        <Route path="/factures" element={<Factures />} />
        <Route path="/alertes" element={<Alertes />} />
      </Routes>
    </Layout>
  )
}

export default App
