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
    reviewerName: 'AI code feedback',
    reviewerRole: 'Automated evaluation',
    avatarUrl: '',
    description: 'High-throughput payment gateway routines, ledger consistency, and low-latency API handlers.'
  },
  'Enterprise SaaS': {
    teamName: 'Platform Core · SaaS Engineering',
    reviewerName: 'AI code feedback',
    reviewerRole: 'Automated evaluation',
    avatarUrl: '',
    description: 'Multi-tenant architecture, automated provisioning, and strict enterprise security controls.'
  },
  'AI Startup': {
    teamName: 'Applied AI & Systems Team',
    reviewerName: 'AI code feedback',
    reviewerRole: 'Automated evaluation',
    avatarUrl: '',
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
    reviewerName: 'AI code feedback',
    reviewerRole: 'Automated evaluation',
    avatarUrl: '',
    description: 'Core product engineering and infrastructure maintenance.'
  };
}

export function formatTicketId(taskId?: string | null): string {
  if (!taskId) return 'Task';
  const clean = taskId.replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  return `Task ${clean.slice(0, 8)}`;
}
