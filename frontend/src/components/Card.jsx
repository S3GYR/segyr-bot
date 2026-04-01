import React from 'react'
import { motion } from 'framer-motion'

export default function Card({ children, className = '', hover = true }) {
  return (
    <motion.div
      whileHover={hover ? { scale: 1.02, boxShadow: '0 15px 40px rgba(0,0,0,0.35)' } : undefined}
      whileTap={hover ? { scale: 0.99 } : undefined}
      transition={{ type: 'spring', stiffness: 260, damping: 18 }}
      className={`rounded-2xl border border-[#1F2937] bg-[#121826]/90 shadow-lg shadow-black/20 ${className}`}
    >
      {children}
    </motion.div>
  )
}
