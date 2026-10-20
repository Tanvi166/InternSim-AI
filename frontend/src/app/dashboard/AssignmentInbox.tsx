'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { formatTicketId } from '@/lib/companyConfig';
import { StatusBadge } from '@/components/StatusBadge';
import { 
  Inbox, 
  Clock, 
  CheckCircle2, 
  AlertCircle, 
  ArrowRight, 
  FileCode2, 
  Bug, 
  Sparkles, 
  FileText, 
  RotateCcw,
  Calendar,
  Layers,
  ChevronRight,
  Filter
} from 'lucide-react';

export interface AssignmentItem {
  taskId: string;
  formattedId: string;
  title: string;
  description: string;
  category: 'bug-fix' | 'feature-dev' | 'refactor' | 'documentation';
  priority: 'P0 CRITICAL' | 'P1 HIGH' | 'P2 MEDIUM';
  status: 'inbox' | 'in_progress' | 'review_requested' | 'completed';
  language: string;
  difficultyLevel: number;
  projectTitle?: string;
  dueDateLabel?: string;
  lastScore?: number | null;
  lastCorrectness?: number | null;
  lastQuality?: number | null;
  isPassed: boolean;
  attemptCount: number;
}

interface AssignmentInboxProps {
  assignments: AssignmentItem[];
  activeTaskId?: string | null;
}

export default function AssignmentInbox({ assignments, activeTaskId }: AssignmentInboxProps) {
  const [activeTab, setActiveTab] = useState<'all' | 'inbox' | 'in_progress' | 'review_requested' | 'completed'>('all');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');

  const filteredAssignments = assignments.filter((item) => {
    // Tab filter
    if (activeTab === 'inbox' && item.status !== 'inbox') return false;
    if (activeTab === 'in_progress' && item.status !== 'in_progress') return false;
    if (activeTab === 'review_requested' && item.status !== 'review_requested') return false;
    if (activeTab === 'completed' && item.status !== 'completed') return false;

    // Category filter
    if (selectedCategory !== 'all' && item.category !== selectedCategory) return false;

    return true;
  });

  const countByStatus = {
    all: assignments.length,
    inbox: assignments.filter(a => a.status === 'inbox').length,
    in_progress: assignments.filter(a => a.status === 'in_progress').length,
    review_requested: assignments.filter(a => a.status === 'review_requested').length,
    completed: assignments.filter(a => a.status === 'completed').length,
  };

  const getCategoryBadge = (category: string) => {
    switch (category) {
      case 'bug-fix':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-rose-950/60 border border-rose-800/80 text-rose-300 text-[10px] font-mono font-medium">
            <Bug className="h-2.5 w-2.5" />
            <span>Bug Fix</span>
          </span>
        );
      case 'feature-dev':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-800/80 text-cyan-300 text-[10px] font-mono font-medium">
            <Sparkles className="h-2.5 w-2.5" />
            <span>Feature Dev</span>
          </span>
        );
      case 'refactor':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-purple-950/60 border border-purple-800/80 text-purple-300 text-[10px] font-mono font-medium">
            <RotateCcw className="h-2.5 w-2.5" />
            <span>Refactor</span>
          </span>
        );
      case 'documentation':
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-950/60 border border-amber-800/80 text-amber-300 text-[10px] font-mono font-medium">
            <FileText className="h-2.5 w-2.5" />
            <span>Docs</span>
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 text-[10px] font-mono">
            <FileCode2 className="h-2.5 w-2.5" />
            <span>{category}</span>
          </span>
        );
    }
  };

  const getPriorityBadge = (priority: string) => {
    if (priority.includes('P0')) {
      return (
        <span className="px-1.5 py-0.5 rounded bg-rose-950 border border-rose-800 text-rose-400 font-bold text-[10px]">
          {priority}
        </span>
      );
    }
    if (priority.includes('P1')) {
      return (
        <span className="px-1.5 py-0.5 rounded bg-amber-950 border border-amber-800 text-amber-400 font-bold text-[10px]">
          {priority}
        </span>
      );
    }
    return (
      <span className="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-400 font-medium text-[10px]">
        {priority}
      </span>
    );
  };

  const getStatusBadge = (status: AssignmentItem['status']) => {
    switch (status) {
      case 'inbox':
        return <StatusBadge status="neutral" label="Inbox / Assigned" />;
      case 'in_progress':
        return <StatusBadge status="in-progress" label="In Progress" />;
      case 'review_requested':
        return <StatusBadge status="warning" label="Revision Needed" />;
      case 'completed':
        return <StatusBadge status="passed" label="Completed & Merged" />;
    }
  };

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 space-y-6 shadow-xl">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-zinc-800 pb-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-mono text-cyan-400 mb-1">
            <Inbox className="h-3.5 w-3.5" />
            <span>Engineering Assignment Inbox</span>
          </div>
          <h2 className="text-xl font-bold text-zinc-100 tracking-tight">
            Sprint Assignments & Tickets
          </h2>
          <p className="text-xs text-zinc-400 font-mono mt-0.5">
            Active engineering tasks, bug investigations, and pull request reviews assigned to you.
          </p>
        </div>

        {/* Category Filter Dropdown */}
        <div className="flex items-center gap-2">
          <Filter className="h-3.5 w-3.5 text-zinc-500" />
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="bg-zinc-950 border border-zinc-800 text-zinc-300 rounded px-2.5 py-1 text-xs font-mono focus:outline-none focus:border-cyan-500"
          >
            <option value="all">All Categories</option>
            <option value="feature-dev">Feature Development</option>
            <option value="bug-fix">Bug Fix</option>
            <option value="refactor">Refactor</option>
            <option value="documentation">Documentation</option>
          </select>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-1.5 border-b border-zinc-800/80 pb-3 text-xs font-mono">
        <button
          onClick={() => setActiveTab('all')}
          className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 ${
            activeTab === 'all'
              ? 'bg-zinc-800 text-zinc-100 border border-zinc-700 font-semibold'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
        >
          <span>All Assignments</span>
          <span className="px-1.5 py-0.2 rounded-full bg-zinc-900 text-[10px] text-zinc-400">
            {countByStatus.all}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('inbox')}
          className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 ${
            activeTab === 'inbox'
              ? 'bg-zinc-800 text-zinc-100 border border-zinc-700 font-semibold'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
        >
          <Inbox className="h-3 w-3 text-cyan-400" />
          <span>Inbox</span>
          <span className="px-1.5 py-0.2 rounded-full bg-zinc-900 text-[10px] text-zinc-400">
            {countByStatus.inbox}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('in_progress')}
          className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 ${
            activeTab === 'in_progress'
              ? 'bg-zinc-800 text-zinc-100 border border-zinc-700 font-semibold'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
        >
          <Clock className="h-3 w-3 text-amber-400" />
          <span>In Progress</span>
          <span className="px-1.5 py-0.2 rounded-full bg-zinc-900 text-[10px] text-zinc-400">
            {countByStatus.in_progress}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('review_requested')}
          className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 ${
            activeTab === 'review_requested'
              ? 'bg-zinc-800 text-zinc-100 border border-zinc-700 font-semibold'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
        >
          <AlertCircle className="h-3 w-3 text-rose-400" />
          <span>Revision Needed</span>
          <span className="px-1.5 py-0.2 rounded-full bg-zinc-900 text-[10px] text-zinc-400">
            {countByStatus.review_requested}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('completed')}
          className={`px-3 py-1.5 rounded-md transition-colors flex items-center gap-1.5 ${
            activeTab === 'completed'
              ? 'bg-zinc-800 text-zinc-100 border border-zinc-700 font-semibold'
              : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50'
          }`}
        >
          <CheckCircle2 className="h-3 w-3 text-emerald-400" />
          <span>Completed</span>
          <span className="px-1.5 py-0.2 rounded-full bg-zinc-900 text-[10px] text-zinc-400">
            {countByStatus.completed}
          </span>
        </button>
      </div>

      {/* Assignment List */}
      {filteredAssignments.length > 0 ? (
        <div className="space-y-3 font-mono">
          {filteredAssignments.map((assignment) => {
            const isSelectedActive = activeTaskId === assignment.taskId;
            return (
              <div
                key={assignment.taskId}
                className={`p-4 rounded-lg border transition-all ${
                  isSelectedActive
                    ? 'bg-cyan-950/20 border-cyan-500/60 shadow-lg shadow-cyan-500/5'
                    : assignment.isPassed
                    ? 'bg-zinc-950/50 border-emerald-950/80 hover:border-emerald-800/50'
                    : assignment.status === 'review_requested'
                    ? 'bg-amber-950/10 border-amber-900/60 hover:border-amber-800'
                    : 'bg-zinc-950/60 border-zinc-800/80 hover:border-zinc-700'
                }`}
              >
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-2.5 pb-2 border-b border-zinc-800/50">
                  <div className="flex items-center gap-2.5 flex-wrap">
                    <span className="font-bold text-cyan-400 text-xs">
                      {assignment.formattedId}
                    </span>
                    {getCategoryBadge(assignment.category)}
                    {getPriorityBadge(assignment.priority)}
                    {getStatusBadge(assignment.status)}
                  </div>

                  <div className="flex items-center gap-3 text-[11px] text-zinc-500">
                    {assignment.dueDateLabel && (
                      <span className="flex items-center gap-1">
                        <Calendar className="h-3 w-3 text-zinc-400" />
                        <span>Due: {assignment.dueDateLabel}</span>
                      </span>
                    )}
                    <span>Tier Lvl {assignment.difficultyLevel}</span>
                    <span className="uppercase">{assignment.language}</span>
                  </div>
                </div>

                <div className="mt-3 flex flex-col md:flex-row md:items-start justify-between gap-4">
                  <div className="space-y-1.5 flex-1">
                    <h3 className="text-sm font-sans font-semibold text-zinc-100">
                      {assignment.title}
                    </h3>
                    <p className="text-xs text-zinc-400 font-sans line-clamp-2 leading-relaxed">
                      {assignment.description}
                    </p>

                    {assignment.status === 'review_requested' && assignment.lastScore !== null && (
                      <div className="p-2 rounded bg-amber-950/30 border border-amber-800/40 text-amber-300 text-[11px] flex items-center gap-2 mt-2">
                        <AlertCircle className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                        <span>
                          Prior PR scored {assignment.lastScore}/100 (Correctness: {assignment.lastCorrectness}/60, Quality: {assignment.lastQuality}/40). Reopen to revise.
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="flex items-center gap-2 shrink-0 self-end md:self-center">
                    {assignment.isPassed ? (
                      <Link href={`/tasks/${assignment.taskId}`}>
                        <button className="px-3.5 py-1.5 rounded-lg border border-zinc-700 bg-zinc-800/80 hover:bg-zinc-700 text-zinc-200 text-xs font-semibold transition-colors flex items-center gap-1.5">
                          <span>Review Solution</span>
                          <ChevronRight className="h-3 w-3 text-zinc-400" />
                        </button>
                      </Link>
                    ) : (
                      <Link href={`/tasks/${assignment.taskId}`}>
                        <button className="px-4 py-1.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-black text-xs font-semibold transition-colors flex items-center gap-1.5 shadow-md shadow-cyan-500/20">
                          <span>{assignment.status === 'review_requested' ? 'Revise Solution' : 'Open Workspace'}</span>
                          <ArrowRight className="h-3.5 w-3.5" />
                        </button>
                      </Link>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="py-12 text-center font-mono space-y-2 border border-dashed border-zinc-800 rounded-lg">
          <Inbox className="h-8 w-8 text-zinc-600 mx-auto" />
          <h4 className="text-zinc-300 text-xs font-semibold">No assignments found</h4>
          <p className="text-[11px] text-zinc-500 max-w-sm mx-auto">
            No assignments match the selected status or category filter. Switch views or pick up a new ticket above.
          </p>
        </div>
      )}
    </div>
  );
}
