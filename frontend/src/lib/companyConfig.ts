export interface PersonaConfig {
  teamName: string;
  reviewerName: string;
  reviewerRole: string;
  avatarUrl: string;
  description: string;
}

export const PERSONA_CONFIGS: Record<string, PersonaConfig> = {
  'Fintech Startup': {
    teamName: 'Backend Engineering · Fintech Squad',
    reviewerName: 'Sarah Chen',
    reviewerRole: 'Senior Backend Engineer',
    avatarUrl: 'https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?auto=format&fit=crop&w=120&h=120&q=80',
    description: 'High-throughput payment gateway routines, ledger consistency, and low-latency API handlers.'
  },
  'Enterprise SaaS': {
    teamName: 'Platform Core · SaaS Engineering',
    reviewerName: 'Marcus Vance',
    reviewerRole: 'Staff Platform Architect',
    avatarUrl: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=120&h=120&q=80',
    description: 'Multi-tenant architecture, automated provisioning, and strict enterprise security controls.'
  },
  'AI Startup': {
    teamName: 'Applied AI & Systems Team',
    reviewerName: 'Elena Rostova',
    reviewerRole: 'Principal Systems Lead',
    avatarUrl: 'https://images.unsplash.com/photo-1580489944761-15a19d654956?auto=format&fit=crop&w=120&h=120&q=80',
    description: 'Model inference pipelines, prompt routing, evaluation harnesses, and synthetic data streams.'
  }
};

export function getPersonaConfig(persona?: string | null): PersonaConfig {
  if (!persona) {
    return PERSONA_CONFIGS['Enterprise SaaS'];
  }

  // Exact match or partial match
  const key = Object.keys(PERSONA_CONFIGS).find(k => k.toLowerCase() === persona.toLowerCase() || persona.toLowerCase().includes(k.toLowerCase().split(' ')[0]));
  
  return PERSONA_CONFIGS[key || 'Enterprise SaaS'] || {
    teamName: `${persona} · Engineering Team`,
    reviewerName: 'Alex Rivera',
    reviewerRole: 'Senior Staff Engineer',
    avatarUrl: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=120&h=120&q=80',
    description: 'Core product engineering and infrastructure maintenance.'
  };
}

export function formatTicketId(taskId?: string | null): string {
  if (!taskId) return 'PLAT-1024';
  const clean = taskId.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  const hexTail = clean.slice(-4) || '1842';
  return `PLAT-${hexTail}`;
}

export function getSprintMetrics(submissionCount: number) {
  const sprint = Math.floor(submissionCount / 6) + 1;
  const day = (submissionCount % 6) + 1;
  const sprintProgress = Math.min(Math.round(((submissionCount % 6) / 6) * 100), 100);
  return { sprint, day, sprintProgress };
}
