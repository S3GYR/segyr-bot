import React from 'react'
import Card from '../components/Card'
import ChatBox from '../components/ChatBox'

export default function Chat() {
  return (
    <div className="space-y-6">
      <Card className="p-5 shadow-black/20">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-[#E5E7EB]">Chat IA</h1>
            <p className="text-sm text-slate-400">Pilote l'agent SEGYR · modes Auto / Fast / Quality · LLM router.</p>
          </div>
        </div>
      </Card>
      <ChatBox />
    </div>
  )
}
