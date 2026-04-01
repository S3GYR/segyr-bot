import React from 'react'
import Card from './Card'

export default function ChartCard({ title, action, children }) {
  return (
    <Card className="p-4 shadow-black/15">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-base font-semibold text-[#E5E7EB]">{title}</h3>
        {action}
      </div>
      {children}
    </Card>
  )
}
