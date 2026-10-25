'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { FolderPlus, Loader2 } from 'lucide-react';
import { createClient } from '@/utils/supabase/client';

interface StartNewProjectButtonProps {
  persona: string;
  isCurrentCompleted: boolean;
  className?: string;
}

export default function StartNewProjectButton({
  persona,
  isCurrentCompleted,
  className = ''
}: StartNewProjectButtonProps) {
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleStartNewProject = async () => {
    // If not completed, confirm before abandoning
    if (!isCurrentCompleted) {
      const confirmed = window.confirm(
        'Your current project is not yet completed. Are you sure you want to abandon it and start a brand-new project with a clean codebase?'
      );
      if (!confirmed) return;
    }

    setLoading(true);
    toast.info('Creating a new project...', {
      description: 'Setting up a new project and ticket sequence.',
    });

    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;

      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const res = await fetch(`${apiUrl}/api/projects/new`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          persona,
          language: 'python',
          target_tickets: 4,
          abandon_current: !isCurrentCompleted
        })
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || 'Failed to start new project');
      }

      const newProj = await res.json();
      toast.success('New project created', {
        description: `${newProj.title} is ready for its first ticket.`,
      });

      router.refresh();
    } catch (err: unknown) {
      console.error('Start new project error:', err);
      const errMsg = err instanceof Error ? err.message : 'Failed to initialize project.';
      toast.error('Project Creation Error', { description: errMsg });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Button
      onClick={handleStartNewProject}
      disabled={loading}
      className={`bg-emerald-500 hover:bg-emerald-400 text-black font-semibold text-xs h-10 px-5 gap-2 shadow-lg shadow-emerald-500/20 ${className}`}
    >
      {loading ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" />
          <span>Setting up Project...</span>
        </>
      ) : (
        <>
          <FolderPlus className="h-4 w-4" />
          <span>Start Next Internship Project</span>
        </>
      )}
    </Button>
  );
}
