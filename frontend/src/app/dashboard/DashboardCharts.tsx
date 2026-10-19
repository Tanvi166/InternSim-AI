'use client'

import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

export default function DashboardCharts({ data }: { data: any[] }) {
  const chartData = (data || []).map((d, index) => ({
    name: `Task ${index + 1}`,
    score: d?.total_score ?? 0
  }))

  return (
    <div className="h-64 w-full bg-card border rounded-lg p-4 shadow-sm">
      <h3 className="font-semibold mb-4 text-sm text-muted-foreground">Score Trend</h3>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
          <Line type="monotone" dataKey="score" stroke="#8884d8" strokeWidth={2} />
          <CartesianGrid stroke="#ccc" strokeDasharray="5 5" />
          <XAxis dataKey="name" fontSize={12} />
          <YAxis fontSize={12} domain={[0, 100]} />
          <Tooltip />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
