'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { 
  Terminal, 
  LayoutDashboard, 
  TrendingUp, 
  LogOut, 
  Building2, 
  CheckCircle2,
  ShieldCheck
} from 'lucide-react';
import { logout } from '@/app/dashboard/actions';
import { Button } from '@/components/ui/button';

interface AppShellProps {
  children: React.ReactNode;
  userEmail?: string;
  userSkill?: string;
  userPersona?: string;
}

export function AppShell({ children, userEmail, userSkill, userPersona }: AppShellProps) {
  const pathname = usePathname();

  const navItems = [
    {
      label: 'Workspace',
      href: '/dashboard',
      icon: LayoutDashboard,
      active: pathname === '/dashboard' || pathname.startsWith('/tasks')
    },
    {
      label: 'Engineering Progression',
      href: '/progress',
      icon: TrendingUp,
      active: pathname === '/progress'
    }
  ];

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col font-sans selection:bg-cyan-500 selection:text-black">
      {/* Top Engineering Nav */}
      <header className="h-14 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md sticky top-0 z-40 px-4 md:px-6 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/dashboard" className="flex items-center gap-2.5 group">
            <div className="h-8 w-8 rounded-lg bg-zinc-900 border border-zinc-700/80 flex items-center justify-center text-cyan-400 group-hover:border-cyan-500/50 transition-colors">
              <Terminal className="h-4 w-4" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-sm tracking-tight text-zinc-100">Nexora</span>
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400 border border-zinc-700/60">Platform</span>
              </div>
              <p className="text-[11px] text-zinc-400 font-mono leading-none mt-0.5">Engineering Simulation</p>
            </div>
          </Link>

          <nav className="hidden md:flex items-center gap-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                    item.active
                      ? 'bg-zinc-800/90 text-zinc-100 border border-zinc-700/70'
                      : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900'
                  }`}
                >
                  <Icon className={`h-3.5 w-3.5 ${item.active ? 'text-cyan-400' : 'text-zinc-400'}`} />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="flex items-center gap-3">
          {userPersona && (
            <div className="hidden lg:flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-zinc-900 border border-zinc-800 text-xs text-zinc-300 font-mono">
              <Building2 className="h-3 w-3 text-cyan-400" />
              <span>{userPersona}</span>
            </div>
          )}

          {userSkill && (
            <div className="hidden sm:flex items-center gap-1 px-2 py-1 rounded bg-zinc-900 border border-zinc-800 text-[11px] text-zinc-400 font-mono">
              <ShieldCheck className="h-3 w-3 text-emerald-400" />
              <span>Lvl: {userSkill}</span>
            </div>
          )}

          <div className="h-4 w-px bg-zinc-800 hidden sm:block" />

          {userEmail && (
            <div className="text-xs text-zinc-400 hidden sm:block font-mono truncate max-w-[140px]">
              {userEmail}
            </div>
          )}

          <form action={logout}>
            <Button
              variant="outline"
              size="sm"
              className="h-8 text-xs bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border-zinc-800 hover:border-zinc-700 gap-1.5"
            >
              <LogOut className="h-3.5 w-3.5 text-zinc-400" />
              <span className="hidden sm:inline">Exit</span>
            </Button>
          </form>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 md:px-6 py-6">
        {children}
      </main>

      {/* Corporate Footer */}
      <footer className="border-t border-zinc-800/60 bg-zinc-950 py-4 px-4 md:px-6 text-xs text-zinc-400 font-mono flex flex-col sm:flex-row justify-between items-center gap-2">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
          <span>Nexora Platform Engineering System · v2.4.0-prod</span>
        </div>
        <p className="text-zinc-400">InternSim AI Infrastructure · All tickets real-time evaluated</p>
      </footer>
    </div>
  );
}
