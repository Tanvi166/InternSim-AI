import Link from 'next/link';
import { createClient } from '@/utils/supabase/server';
import { redirect } from 'next/navigation';
import { 
  Terminal, 
  ArrowRight, 
  CheckCircle2, 
  XCircle, 
  Cpu, 
  GitPullRequest, 
  ShieldCheck, 
  Layers, 
  Code2, 
  FileCode2, 
  ChevronRight,
  Zap,
  Building2
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/StatusBadge';

export default async function Home() {
  const supabase = await createClient();
  const { data: { user } } = await supabase.auth.getUser();
  
  if (user) {
    redirect('/dashboard');
  }

  const comparison = [
    {
      title: 'Traditional LeetCode & Practice Sites',
      icon: XCircle,
      iconColor: 'text-rose-400',
      borderColor: 'border-rose-900/30',
      bgColor: 'bg-rose-950/10',
      points: [
        'Isolated algorithm puzzles out of real context',
        'Arbitrary speed benchmarks and memory trivia',
        'No code review, architecture, or style feedback',
        'Prepares you for interviews, not engineering jobs'
      ]
    },
    {
      title: 'InternSim AI Virtual Company',
      icon: Terminal,
      iconColor: 'text-cyan-400',
      borderColor: 'border-cyan-500/40',
      bgColor: 'bg-cyan-950/20',
      featured: true,
      points: [
        'Real sprint tickets derived from actual SaaS architectures',
        'Automated execution against hidden regression suites',
        'Instant senior engineer PR code review & readability scores',
        'Adaptive difficulty tier progression as your code improves'
      ]
    },
    {
      title: 'Real Engineering Team at Scale',
      icon: CheckCircle2,
      iconColor: 'text-emerald-400',
      borderColor: 'border-emerald-900/30',
      bgColor: 'bg-emerald-950/10',
      points: [
        'Pick up sprint tickets from product backlog',
        'Adhere to team conventions, style, and edge cases',
        'Pass CI/CD test suite and peer code review',
        'Ship production-ready features safely'
      ]
    }
  ];

  const steps = [
    { num: '01', title: 'Join Org', desc: 'Step into Nexora Platform Engineering as a Junior Software Engineer.' },
    { num: '02', title: 'Get Role', desc: 'Choose your focus: Fintech Squad, Enterprise SaaS, or Applied AI.' },
    { num: '03', title: 'Receive Ticket', desc: 'Pick up real JIRA-style tickets (e.g. PLAT-1842 Subdomain Generator).' },
    { num: '04', title: 'Investigate', desc: 'Analyze specifications, constraints, edge cases, and starter codebase.' },
    { num: '05', title: 'Ship Solution', desc: 'Write clean, maintainable code directly in the integrated workspace.' },
    { num: '06', title: 'Hidden Suite', desc: 'Run code against automated regression tests via sandbox execution.' },
    { num: '07', title: 'Code Review', desc: 'Receive instant senior engineer PR feedback on readability and structure.' },
    { num: '08', title: 'Level Up', desc: 'Score 75%+ across sprint submissions to automatically tier up.' }
  ];

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-cyan-500 selection:text-black flex flex-col">
      {/* Header */}
      <header className="h-16 border-b border-zinc-800/80 bg-zinc-950/80 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-zinc-900 border border-zinc-700/80 flex items-center justify-center text-cyan-400">
            <Terminal className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-base tracking-tight text-zinc-100">InternSim AI</span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950/80 text-cyan-400 border border-cyan-800/60 uppercase">Virtual Enterprise</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Link href="/login">
            <Button variant="ghost" className="text-zinc-300 hover:text-white hover:bg-zinc-900 text-xs">
              Log In
            </Button>
          </Link>
          <Link href="/login">
            <Button size="sm" className="bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs gap-1.5 shadow-lg shadow-cyan-500/20">
              Enter Company
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative pt-16 pb-20 px-6 max-w-7xl mx-auto w-full text-center flex flex-col items-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-zinc-900 border border-zinc-800 text-xs font-mono text-cyan-400 mb-6">
          <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
          <span>Nexora Platform Engineering System</span>
        </div>

        <h1 className="text-4xl md:text-6xl font-bold tracking-tight max-w-4xl text-zinc-100 leading-[1.15]">
          Work like an engineer. <br />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 via-teal-300 to-emerald-400">
            Before you become one.
          </span>
        </h1>

        <p className="mt-6 text-base md:text-lg text-zinc-400 max-w-2xl font-normal leading-relaxed">
          Step into a simulated software enterprise. Receive sprint tickets, investigate bugs, ship solutions, and get instant senior PR code reviews — not algorithm puzzles.
        </p>

        <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4 w-full max-w-md">
          <Link href="/login" className="w-full sm:w-auto">
            <Button size="lg" className="w-full sm:w-auto bg-cyan-500 hover:bg-cyan-400 text-black font-bold px-8 shadow-xl shadow-cyan-500/25 gap-2">
              Enter the Company
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <a href="#how-it-works" className="w-full sm:w-auto">
            <Button size="lg" variant="outline" className="w-full sm:w-auto border-zinc-800 text-zinc-300 hover:bg-zinc-900 hover:border-zinc-700">
              See How It Works
            </Button>
          </a>
        </div>

        {/* Hero Visual Mockup Component */}
        <div className="mt-14 w-full max-w-5xl rounded-xl border border-zinc-800 bg-zinc-900/60 p-2 shadow-2xl backdrop-blur-sm text-left">
          <div className="h-8 bg-zinc-950 rounded-t-lg border-b border-zinc-800 px-4 flex items-center justify-between text-xs font-mono text-zinc-500">
            <div className="flex items-center gap-2">
              <span className="h-3 w-3 rounded-full bg-zinc-800" />
              <span className="h-3 w-3 rounded-full bg-zinc-800" />
              <span className="h-3 w-3 rounded-full bg-zinc-800" />
              <span className="ml-2 text-zinc-400 font-semibold">Nexora Workspace — PLAT-1842</span>
            </div>
            <div className="flex items-center gap-2">
              <StatusBadge status="in-progress" label="Sprint Ticket · Active" />
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 p-4 bg-zinc-950/80 rounded-b-lg">
            {/* Left Mock Panel */}
            <div className="space-y-3 p-4 rounded-lg bg-zinc-900/70 border border-zinc-800/80 text-xs">
              <div className="flex items-center justify-between text-zinc-400 font-mono">
                <span>TICKET ID: PLAT-1842</span>
                <span className="text-cyan-400">P1 - HIGH</span>
              </div>
              <h4 className="font-semibold text-sm text-zinc-100">Fix Tenant Subdomain Generator</h4>
              <p className="text-zinc-400 text-xs leading-relaxed">
                In our Enterprise SaaS platform, onboarding automatically generates tenant subdomains from company names. Convert to lowercase and replace spaces with hyphens.
              </p>
              <div className="pt-2 border-t border-zinc-800 font-mono text-[11px] text-zinc-500">
                Team: Backend Engineering · Fintech Squad
              </div>
            </div>

            {/* Center Code Editor Mock */}
            <div className="lg:col-span-2 space-y-3 p-4 rounded-lg bg-zinc-900/90 border border-zinc-800 font-mono text-xs">
              <div className="flex items-center justify-between border-b border-zinc-800 pb-2 text-zinc-400">
                <span className="flex items-center gap-1.5 text-zinc-200">
                  <FileCode2 className="h-3.5 w-3.5 text-cyan-400" />
                  subdomain.py
                </span>
                <span className="text-[10px] text-zinc-500">Python 3.10</span>
              </div>
              <pre className="text-zinc-300 leading-relaxed text-[11px] overflow-x-auto">
                <span className="text-purple-400">def</span> <span className="text-blue-400">generate_subdomain</span>(company_name: <span className="text-teal-300">str</span>) -&gt; <span className="text-teal-300">str</span>:<br />
                {"    "}<span className="text-zinc-500"># Convert to lowercase and replace space characters</span><br />
                {"    "}<span className="text-purple-400">return</span> company_name.lower().replace(<span className="text-amber-300">" "</span>, <span className="text-amber-300">"-"</span>)
              </pre>

              <div className="pt-3 border-t border-zinc-800/80 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <StatusBadge status="passed" label="3/3 Tests Passed" />
                  <span className="text-emerald-400 text-[11px]">Score: 92/100</span>
                </div>
                <div className="text-[11px] text-zinc-400">
                  Reviewed by <span className="text-zinc-200 font-medium">Sarah Chen, Senior Backend Engineer</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Comparison Section */}
      <section className="py-20 px-6 bg-zinc-900/30 border-y border-zinc-800/60">
        <div className="max-w-7xl mx-auto">
          <div className="text-center max-w-3xl mx-auto mb-16">
            <h2 className="text-2xl md:text-4xl font-bold tracking-tight text-zinc-100">
              This is not a practice course.
            </h2>
            <p className="mt-3 text-zinc-400 text-sm md:text-base">
              See how InternSim AI bridges the gap between raw DSA puzzles and actual production engineering.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {comparison.map((c, i) => {
              const Icon = c.icon;
              return (
                <div
                  key={i}
                  className={`p-6 rounded-xl border ${c.borderColor} ${c.bgColor} relative flex flex-col justify-between`}
                >
                  {c.featured && (
                    <span className="absolute -top-3 left-6 px-2.5 py-0.5 rounded-full bg-cyan-500 text-black text-[10px] font-bold font-mono uppercase tracking-wider">
                      InternSim Approach
                    </span>
                  )}
                  <div>
                    <div className="flex items-center gap-3 mb-4">
                      <Icon className={`h-6 w-6 ${c.iconColor}`} />
                      <h3 className="font-semibold text-base text-zinc-100">{c.title}</h3>
                    </div>
                    <ul className="space-y-3">
                      {c.points.map((p, idx) => (
                        <li key={idx} className="flex items-start gap-2.5 text-xs text-zinc-300 leading-relaxed">
                          <ChevronRight className="h-3.5 w-3.5 text-zinc-500 shrink-0 mt-0.5" />
                          <span>{p}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* How It Works (8 Steps) */}
      <section id="how-it-works" className="py-20 px-6 max-w-7xl mx-auto w-full">
        <div className="text-center max-w-3xl mx-auto mb-16">
          <h2 className="text-2xl md:text-4xl font-bold tracking-tight text-zinc-100">
            How the Simulation Works
          </h2>
          <p className="mt-3 text-zinc-400 text-sm md:text-base">
            From onboarding to senior review — experience the complete software delivery lifecycle.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {steps.map((s, idx) => (
            <div key={idx} className="p-5 rounded-lg bg-zinc-900/60 border border-zinc-800/80 hover:border-zinc-700 transition-colors">
              <div className="text-xs font-mono text-cyan-400 font-semibold mb-2">{s.num}</div>
              <h4 className="font-semibold text-sm text-zinc-100 mb-1">{s.title}</h4>
              <p className="text-xs text-zinc-400 leading-relaxed">{s.desc}</p>
            </div>
          ))}
        </div>

        <div className="mt-16 text-center">
          <Link href="/login">
            <Button size="lg" className="bg-cyan-500 hover:bg-cyan-400 text-black font-bold px-8 shadow-xl shadow-cyan-500/20">
              Start Your First Ticket
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
          </Link>
        </div>
      </section>

      {/* Footer */}
      <footer className="mt-auto border-t border-zinc-800/80 bg-zinc-950 py-8 px-6 text-xs text-zinc-500 font-mono text-center">
        <p>Nexora Platform Engineering System · Powered by InternSim AI</p>
      </footer>
    </div>
  );
}
