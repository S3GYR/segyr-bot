import React from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Chat from './pages/Chat'
import Monitoring from './pages/Monitoring'
import Logs from './pages/Logs'
import System from './pages/System'

function App() {
  const location = useLocation()

  return (
    <Layout>
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          <Route path="/" element={<PageWrapper><Dashboard /></PageWrapper>} />
          <Route path="/chat" element={<PageWrapper><Chat /></PageWrapper>} />
          <Route path="/monitoring" element={<PageWrapper><Monitoring /></PageWrapper>} />
          <Route path="/logs" element={<PageWrapper><Logs /></PageWrapper>} />
          <Route path="/system" element={<PageWrapper><System /></PageWrapper>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AnimatePresence>
    </Layout>
  )
}

export default App

function PageWrapper({ children }) {
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
      {children}
    </motion.div>
  )
}
