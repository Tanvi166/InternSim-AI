'use client';

import { useState, useEffect } from 'react';
import { toast } from 'sonner';
import { 
  Building2, 
  Cpu, 
  CreditCard, 
  Layers, 
  ShieldCheck, 
  ArrowRight, 
  Loader2,
  CheckCircle2
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { PERSONA_CONFIGS } from '@/lib/companyConfig';

interface OnboardingFormProps {
  initialError?: string;
  completeOnboardingAction: (formData: FormData) => Promise<void>;
}

export function OnboardingForm({ initialError, completeOnboardingAction }: OnboardingFormProps) {
  const [skillLevel, setSkillLevel] = useState<string>('Beginner');
  const [persona, setPersona] = useState<string>('Enterprise SaaS');
  const [loading, setLoading] = useState<boolean>(false);

  useEffect(() => {
    if (initialError) {
      toast.error('Onboarding Error', { description: initialError });
    }
  }, [initialError]);

  const personas = [
    {
      id: 'Enterprise SaaS',
      title: 'Enterprise SaaS',
      badge: 'Platform Core',
      icon: Building2,
      description: PERSONA_CONFIGS['Enterprise SaaS'].description
    },
    {
      id: 'Fintech Startup',
      title: 'Fintech Startup',
      badge: 'Ledger & Payments',
      icon: CreditCard,
      description: PERSONA_CONFIGS['Fintech Startup'].description
    },
    {
      id: 'AI Startup',
      title: 'Applied AI Startup',
      badge: 'Inference & Systems',
      icon: Cpu,
      description: PERSONA_CONFIGS['AI Startup'].description
    }
  ];

  const skillLevels = [
    {
      id: 'Beginner',
      label: 'Associate / Junior',
      desc: '0-1 years. Focus on core syntax, function signatures, and simple bugs.'
    },
    {
      id: 'Intermediate',
      label: 'Mid-Level Engineer',
      desc: '1-3 years. Focus on complex business logic, edge cases, and performance.'
    }
  ];

  return (
    <form
      action={completeOnboardingAction}
      onSubmit={() => setLoading(true)}
      className="w-full max-w-3xl bg-zinc-900/90 border border-zinc-800 rounded-xl shadow-2xl overflow-hidden backdrop-blur-md"
    >
      {/* Hidden inputs to send state with native Form submission */}
      <input type="hidden" name="skill_level" value={skillLevel} />
      <input type="hidden" name="persona" value={persona} />

      {/* Header */}
      <div className="p-6 md:p-8 border-b border-zinc-800/80 bg-zinc-950/60">
        <div className="flex items-center gap-2 text-cyan-400 font-mono text-xs font-semibold uppercase tracking-wider mb-1">
          <Layers className="h-4 w-4" />
          Engineering Placement Onboarding
        </div>
        <h1 className="text-2xl font-bold text-zinc-100 tracking-tight">
          Select Your Engineering Squad
        </h1>
        <p className="text-xs text-zinc-400 font-mono mt-1">
          Configure your team placement and initial difficulty tier at Nexora Platform Engineering.
        </p>
      </div>

      <div className="p-6 md:p-8 space-y-8">
        {initialError && (
          <div className="p-3 rounded-lg bg-rose-950/40 border border-rose-800/60 text-rose-300 text-xs font-mono">
            {initialError}
          </div>
        )}

        {/* Persona Card Selection */}
        <div className="space-y-3">
          <label className="text-xs font-mono text-zinc-300 font-semibold uppercase tracking-wider block">
            1. Select Team Placement (Persona)
          </label>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {personas.map((p) => {
              const Icon = p.icon;
              const isSelected = persona === p.id;
              return (
                <div
                  key={p.id}
                  onClick={() => setPersona(p.id)}
                  className={`p-4 rounded-xl border text-left cursor-pointer transition-all relative flex flex-col justify-between ${
                    isSelected
                      ? 'bg-cyan-950/30 border-cyan-500/80 shadow-lg shadow-cyan-500/10'
                      : 'bg-zinc-950/60 border-zinc-800/80 hover:border-zinc-700 hover:bg-zinc-900/40'
                  }`}
                >
                  {isSelected && (
                    <CheckCircle2 className="h-4 w-4 text-cyan-400 absolute top-3.5 right-3.5" />
                  )}
                  <div>
                    <div className="h-8 w-8 rounded-lg bg-zinc-900 border border-zinc-800 flex items-center justify-center text-cyan-400 mb-3">
                      <Icon className="h-4 w-4" />
                    </div>
                    <span className="text-[10px] font-mono uppercase px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700/60">
                      {p.badge}
                    </span>
                    <h3 className="font-semibold text-sm text-zinc-100 mt-2">{p.title}</h3>
                    <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed">
                      {p.description}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Skill Level Selection */}
        <div className="space-y-3">
          <label className="text-xs font-mono text-zinc-300 font-semibold uppercase tracking-wider block">
            2. Initial Engineering Level
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {skillLevels.map((s) => {
              const isSelected = skillLevel === s.id;
              return (
                <div
                  key={s.id}
                  onClick={() => setSkillLevel(s.id)}
                  className={`p-4 rounded-xl border text-left cursor-pointer transition-all flex items-start justify-between ${
                    isSelected
                      ? 'bg-emerald-950/30 border-emerald-500/80 shadow-lg shadow-emerald-500/10'
                      : 'bg-zinc-950/60 border-zinc-800/80 hover:border-zinc-700 hover:bg-zinc-900/40'
                  }`}
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <ShieldCheck className={`h-4 w-4 ${isSelected ? 'text-emerald-400' : 'text-zinc-500'}`} />
                      <span className="font-semibold text-sm text-zinc-100">{s.label}</span>
                    </div>
                    <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed">
                      {s.desc}
                    </p>
                  </div>
                  {isSelected && (
                    <CheckCircle2 className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Footer CTA */}
      <div className="p-6 md:p-8 border-t border-zinc-800/80 bg-zinc-950/60 flex flex-col sm:flex-row items-center justify-between gap-4">
        <div className="text-xs text-zinc-400 font-mono">
          Ready to receive diagnostic ticket PLAT-1001
        </div>
        <Button
          type="submit"
          disabled={loading}
          className="w-full sm:w-auto bg-cyan-500 hover:bg-cyan-400 text-black font-semibold text-xs h-10 px-6 gap-2 shadow-lg shadow-cyan-500/20"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Joining Squad...</span>
            </>
          ) : (
            <>
              <span>Confirm Placement & Enter Workspace</span>
              <ArrowRight className="h-4 w-4" />
            </>
          )}
        </Button>
      </div>
    </form>
  );
}
