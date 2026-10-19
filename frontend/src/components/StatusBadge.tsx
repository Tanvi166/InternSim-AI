import React from 'react';

export type StatusType = 
  | 'in-progress' 
  | 'passed' 
  | 'review' 
  | 'warning' 
  | 'failed' 
  | 'neutral';

interface StatusBadgeProps {
  status: StatusType;
  label?: string;
  className?: string;
}

export function StatusBadge({ status, label, className = '' }: StatusBadgeProps) {
  let badgeStyles = 'bg-zinc-800 text-zinc-300 border-zinc-700';
  let dotStyles = 'bg-zinc-400';
  let defaultLabel = 'Neutral';

  switch (status) {
    case 'in-progress':
      badgeStyles = 'bg-sky-950/60 text-sky-400 border-sky-800/60';
      dotStyles = 'bg-sky-400 animate-pulse';
      defaultLabel = 'In Progress';
      break;
    case 'passed':
      badgeStyles = 'bg-emerald-950/60 text-emerald-400 border-emerald-800/60';
      dotStyles = 'bg-emerald-400';
      defaultLabel = 'Tests Passed';
      break;
    case 'review':
    case 'warning':
      badgeStyles = 'bg-amber-950/60 text-amber-400 border-amber-800/60';
      dotStyles = 'bg-amber-400';
      defaultLabel = 'Code Review';
      break;
    case 'failed':
      badgeStyles = 'bg-rose-950/60 text-rose-400 border-rose-800/60';
      dotStyles = 'bg-rose-400';
      defaultLabel = 'Action Needed';
      break;
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-mono font-medium border ${badgeStyles} ${className}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${dotStyles}`} />
      {label || defaultLabel}
    </span>
  );
}
