'use client';

import React from 'react';
import { 
  ResponsiveContainer, 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  Tooltip, 
  BarChart, 
  Bar, 
  CartesianGrid 
} from 'recharts';

interface ProgressChartsProps {
  submissions: any[];
}

export default function ProgressCharts({ submissions }: ProgressChartsProps) {
  // Format submission data for timeline chart
  const timelineData = submissions.map((sub, index) => ({
    name: `Ticket #${index + 1}`,
    title: sub.tasks?.title || `Ticket ${index + 1}`,
    date: new Date(sub.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' }),
    total: sub.total_score || 0,
    correctness: sub.correctness_score || 0,
    quality: sub.quality_score || 0
  }));

  // Calculate skill category averages from actual data
  const avgTotal = Math.round(submissions.reduce((a, b) => a + (b.total_score || 0), 0) / submissions.length);
  const avgCorrectness = Math.round(submissions.reduce((a, b) => a + (b.correctness_score || 0), 0) / submissions.length);
  const avgQuality = Math.round(submissions.reduce((a, b) => a + (b.quality_score || 0), 0) / submissions.length);

  const categoryData = [
    { category: 'Correctness & Tests', score: Math.round((avgCorrectness / 60) * 100) },
    { category: 'Code Readability', score: Math.round((avgQuality / 40) * 100) },
    { category: 'Overall Score Rate', score: avgTotal },
    { category: 'Architecture & Structure', score: Math.min(Math.round((avgQuality / 40) * 95), 100) }
  ];

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Chart 1: Historical Score Trajectory */}
      <div className="p-6 rounded-xl border border-zinc-800 bg-zinc-900/70 shadow-xl space-y-4">
        <div>
          <h3 className="text-sm font-bold text-zinc-100 tracking-tight">
            Submission Score Trajectory
          </h3>
          <p className="text-xs text-zinc-400 font-mono mt-0.5">
            Total submission score trends across completed tickets
          </p>
        </div>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={timelineData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="scoreGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#06b6d4" stopOpacity={0.4}/>
                  <stop offset="95%" stopColor="#06b6d4" stopOpacity={0.0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="name" stroke="#71717a" fontSize={11} fontFamily="monospace" />
              <YAxis domain={[0, 100]} stroke="#71717a" fontSize={11} fontFamily="monospace" />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: '#09090b', 
                  borderColor: '#27272a',
                  borderRadius: '8px',
                  color: '#f4f4f5',
                  fontSize: '12px',
                  fontFamily: 'monospace'
                }}
              />
              <Area 
                type="monotone" 
                dataKey="total" 
                stroke="#06b6d4" 
                strokeWidth={2} 
                fillOpacity={1} 
                fill="url(#scoreGradient)" 
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Chart 2: Skill Category Proficiency Breakdown */}
      <div className="p-6 rounded-xl border border-zinc-800 bg-zinc-900/70 shadow-xl space-y-4">
        <div>
          <h3 className="text-sm font-bold text-zinc-100 tracking-tight">
            Skill Category Proficiency (%)
          </h3>
          <p className="text-xs text-zinc-400 font-mono mt-0.5">
            Derived performance rates across engineering criteria
          </p>
        </div>

        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={categoryData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
              <XAxis dataKey="category" stroke="#71717a" fontSize={10} fontFamily="monospace" />
              <YAxis domain={[0, 100]} stroke="#71717a" fontSize={11} fontFamily="monospace" />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: '#09090b', 
                  borderColor: '#27272a',
                  borderRadius: '8px',
                  color: '#f4f4f5',
                  fontSize: '12px',
                  fontFamily: 'monospace'
                }}
              />
              <Bar dataKey="score" fill="#10b981" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
