'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Activity,
  ArrowUpRight,
  BriefcaseBusiness,
  Code2,
  FolderKanban,
  LogOut,
  Terminal,
} from 'lucide-react';
import { logout } from '@/app/dashboard/actions';
import { Button } from '@/components/ui/button';

interface AppShellProps {
  children: React.ReactNode;
  userEmail?: string;
  userSkill?: string;
  userPersona?: string;
}

const navItems = [
  { label: 'Overview', href: '/dashboard', icon: Activity, matches: (path: string) => path === '/dashboard' || path.startsWith('/tasks/') },
  { label: 'My Projects', href: '/projects', icon: FolderKanban, matches: (path: string) => path.startsWith('/projects') },
  { label: 'GitHub', href: '/github', icon: Code2, matches: (path: string) => path.startsWith('/github') },
  { label: 'Career Progress', href: '/progress', icon: BriefcaseBusiness, matches: (path: string) => path.startsWith('/progress') },
];

export function AppShell({ children, userEmail, userSkill, userPersona }: AppShellProps) {
  const pathname = usePathname();
  const initials = userEmail?.trim().slice(0, 1).toUpperCase() || 'I';

  return (
    <div className="min-h-screen bg-[#080b12] text-slate-100 font-sans selection:bg-cyan-300 selection:text-slate-950">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[248px] flex-col border-r border-white/[0.07] bg-[#0b0f18] px-4 py-5 lg:flex">
        <Link href="/dashboard" className="group mb-9 flex items-center gap-3 px-2">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-300 text-slate-950 shadow-[0_8px_28px_-12px_rgba(103,232,249,0.8)] transition-transform group-hover:scale-105">
            <Terminal className="h-5 w-5" />
          </span>
          <span className="min-w-0">
            <span className="block text-sm font-semibold tracking-tight text-white">InternSim AI</span>
            <span className="mt-0.5 block text-[10px] font-medium uppercase tracking-[0.17em] text-slate-500">Career workspace</span>
          </span>
        </Link>

        <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-600">Your workspace</p>
        <nav aria-label="Main navigation" className="space-y-1">
          {navItems.map(({ label, href, icon: Icon, matches }) => {
            const active = matches(pathname);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? 'page' : undefined}
                className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-colors ${active ? 'bg-cyan-300/[0.09] text-cyan-100 ring-1 ring-inset ring-cyan-200/10' : 'text-slate-400 hover:bg-white/[0.04] hover:text-slate-100'}`}
              >
                {active && <span className="absolute inset-y-2.5 left-0 w-[2px] rounded-r-full bg-cyan-300" />}
                <Icon className={`h-[17px] w-[17px] ${active ? 'text-cyan-300' : 'text-slate-500 group-hover:text-slate-300'}`} />
                {label}
                {href === '/github' && <ArrowUpRight className="ml-auto h-3.5 w-3.5 opacity-50" />}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto rounded-2xl border border-white/[0.07] bg-gradient-to-br from-white/[0.045] to-transparent p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-200">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Learning environment
          </div>
          <p className="text-[11px] leading-relaxed text-slate-500">Build project experience through guided engineering tickets.</p>
        </div>
      </aside>

      <div className="lg:pl-[248px]">
        <header className="sticky top-0 z-30 border-b border-white/[0.07] bg-[#080b12]/85 backdrop-blur-xl">
          <div className="mx-auto flex h-[68px] max-w-[1480px] items-center justify-between gap-4 px-4 sm:px-6 xl:px-9">
            <div className="flex min-w-0 items-center gap-3 lg:hidden">
              <Link href="/dashboard" aria-label="InternSim AI home" className="flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-300 text-slate-950">
                <Terminal className="h-4 w-4" />
              </Link>
              <span className="truncate text-sm font-semibold text-white">InternSim AI</span>
            </div>
            <nav aria-label="Mobile navigation" className="hidden flex-1 items-center gap-1 overflow-x-auto lg:flex">
              <span className="text-xs text-slate-500">Workspace</span>
              <span className="mx-1 text-slate-700">/</span>
              <span className="truncate text-xs font-medium text-slate-200">{navItems.find((item) => item.matches(pathname))?.label ?? 'Overview'}</span>
            </nav>
            <div className="flex flex-1 items-center gap-1 overflow-x-auto lg:hidden" style={{ scrollbarWidth: 'none' }}>
              {navItems.map(({ label, href, icon: Icon, matches }) => {
                const active = matches(pathname);
                return (
                  <Link key={href} href={href} aria-current={active ? 'page' : undefined} className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-2 text-[11px] font-medium ${active ? 'bg-white/[0.07] text-white' : 'text-slate-500 hover:text-slate-200'}`}>
                    <Icon className="h-3.5 w-3.5" />{label}
                  </Link>
                );
              })}
            </div>
            <div className="flex shrink-0 items-center gap-2.5 sm:gap-4">
              {(userSkill || userPersona) && <div className="hidden text-right md:block"><p className="max-w-[180px] truncate text-xs font-medium text-slate-200">{userPersona || 'Engineer'}</p><p className="mt-0.5 text-[10px] text-slate-500">{userSkill ? `${userSkill} level` : 'InternSim workspace'}</p></div>}
              <span className="flex h-8 w-8 items-center justify-center rounded-full border border-cyan-100/15 bg-cyan-200/10 text-xs font-semibold text-cyan-100" title={userEmail}>{initials}</span>
              <form action={logout}>
                <Button type="submit" variant="ghost" size="icon" aria-label="Sign out" title="Sign out" className="h-8 w-8 text-slate-500 hover:bg-white/[0.06] hover:text-white">
                  <LogOut className="h-4 w-4" />
                </Button>
              </form>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1480px] px-4 py-6 sm:px-6 sm:py-8 xl:px-9">{children}</main>
      </div>
    </div>
  );
}
