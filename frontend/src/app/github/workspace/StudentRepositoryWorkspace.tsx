'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Loader2, RefreshCw } from 'lucide-react';
import { createClient } from '@/utils/supabase/client';
import { Button } from '@/components/ui/button';
import TaskEditor from '@/app/tasks/[taskId]/TaskEditor';

interface FileListing {
  repository_id: number;
  repository: string;
  path: string;
  page: number;
  has_more: boolean;
  next_page: number | null;
  items: Array<{ name: string; path: string; type: 'directory' | 'file'; size: number | null }>;
}

interface WorkspaceData {
  repositoryId: number;
  repository: string;
  files: Record<string, string>;
  mainFileName: string;
  language: 'python' | 'javascript';
  skippedFiles: number;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
const MAX_WORKSPACE_FILES = 200;
const MAX_WORKSPACE_BYTES = 10_000_000;
const WORKSPACE_LOAD_TIMEOUT_MS = 30_000;
const BINARY_EXTENSIONS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf', '.zip', '.gz', '.sqlite', '.db',
  '.woff', '.woff2', '.ttf', '.eot', '.mp3', '.mp4', '.mov', '.pyc', '.class', '.so', '.dll',
]);

function extensionOf(path: string) {
  const name = path.split('/').pop() || '';
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot).toLowerCase() : '';
}

export default function StudentRepositoryWorkspace({ userId }: { userId: string }) {
  const [workspace, setWorkspace] = useState<WorkspaceData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadWorkspace = useCallback(async () => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
      setError('Repository loading timed out. Check your GitHub connection and try again.');
      setLoading(false);
    }, WORKSPACE_LOAD_TIMEOUT_MS);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      setError(null);
      setWorkspace(null);
      const token = session?.access_token;
      if (!token || session.user.id !== userId) {
        throw new Error('Your sign-in session changed. Please sign in again.');
      }
      const headers = { Authorization: `Bearer ${token}` };
      const listDirectory = async (path: string) => {
        const items: FileListing['items'] = [];
        let page = 1;
        let first: FileListing | null = null;
        while (true) {
          const query = new URLSearchParams({ path, page: String(page), page_size: '100' });
          const response = await fetch(`${API_URL}/api/github/student-project/files?${query}`, { headers, signal: controller.signal });
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.detail || 'Could not load repository files.');
          const listing = payload as FileListing;
          if (!first) first = listing;
          if (listing.repository_id !== first.repository_id || listing.repository !== first.repository) {
            throw new Error('Repository identity changed while loading. Reload the workspace.');
          }
          items.push(...listing.items);
          if (!listing.has_more || !listing.next_page) break;
          page = listing.next_page;
        }
        return { metadata: first, items };
      };

      const root = await listDirectory('');
      if (!root.metadata?.repository_id) throw new Error('No verified student repository is available. Create your project copy first.');
      const pendingDirectories = [''];
      const filePaths: Array<{ path: string; size: number | null }> = [];
      let skippedFiles = 0;
      while (pendingDirectories.length) {
        const directory = pendingDirectories.shift()!;
        const listing = directory === '' ? root : await listDirectory(directory);
        if (listing.metadata?.repository_id !== root.metadata.repository_id || listing.metadata?.repository !== root.metadata.repository) {
          throw new Error('Repository identity changed while loading. Reload the workspace.');
        }
        for (const item of listing.items) {
          if (item.type === 'directory') pendingDirectories.push(item.path);
          else if (item.size === null || item.size <= 1_000_000) filePaths.push({ path: item.path, size: item.size });
          else skippedFiles += 1;
          if (pendingDirectories.length > 500 || filePaths.length > MAX_WORKSPACE_FILES) {
            throw new Error('This repository is larger than the current browser workspace limit (200 files / 10 MB). Use the read-only browser to inspect it.');
          }
        }
      }

      const candidates = filePaths.filter(({ path }) => !BINARY_EXTENSIONS.has(extensionOf(path)));
      const files: Record<string, string> = {};
      let totalBytes = 0;
      skippedFiles += filePaths.length - candidates.length;
      for (let index = 0; index < candidates.length; index += 5) {
        const batch = await Promise.all(candidates.slice(index, index + 5).map(async ({ path }) => {
          const query = new URLSearchParams({ path });
          const response = await fetch(`${API_URL}/api/github/student-project/file?${query}`, { headers, signal: controller.signal });
          if (response.status === 413 || response.status === 415) return null;
          const payload = await response.json().catch(() => ({}));
          if (!response.ok) throw new Error(payload.detail || `Could not load ${path}.`);
          const file = payload as { repository_id: number; repository: string; path: string; size: number; content: string };
          if (file.repository_id !== root.metadata!.repository_id || file.repository !== root.metadata!.repository) {
            throw new Error('Repository identity changed while loading. Reload the workspace.');
          }
          return file;
        }));
        for (const file of batch) {
          if (!file) { skippedFiles += 1; continue; }
          totalBytes += file.size;
          if (totalBytes > MAX_WORKSPACE_BYTES) throw new Error('Text files exceed the 10 MB local workspace limit. Use the read-only browser to inspect them.');
          files[file.path] = file.content;
        }
      }
      if (Object.keys(files).length === 0) throw new Error('No supported text files were found in the mapped repository.');

      const names = Object.keys(files).sort((a, b) => a.localeCompare(b));
      const mainFileName = ['main.py', 'app.py', 'run.py', 'manage.py'].find((name) => name in files)
        || names.find((name) => name.toLowerCase().endsWith('.py'))
        || ['index.js', 'main.js'].find((name) => name in files)
        || names.find((name) => name.toLowerCase().endsWith('.js'));
      if (!mainFileName) throw new Error('No Python or JavaScript entry file was found. The workspace runner supports those languages only.');
      const language = mainFileName.toLowerCase().endsWith('.js') ? 'javascript' : 'python';
      setWorkspace({ repositoryId: root.metadata.repository_id, repository: root.metadata.repository, files, mainFileName, language, skippedFiles });
    } catch (loadError) {
      const message = loadError instanceof Error ? loadError.message.trim() : '';
      setError(controller.signal.aborted
        ? 'Repository loading timed out. Check your GitHub connection and try again.'
        : message || 'Could not load your repository workspace. Check your GitHub connection and try again.');
    } finally {
      window.clearTimeout(timeoutId);
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (!cancelled) return loadWorkspace();
    });
    return () => { cancelled = true; };
  }, [loadWorkspace]);

  if (loading && !workspace) {
    return <div role="status" className="flex items-center gap-2 rounded-xl border border-zinc-800 bg-zinc-900 p-6 text-sm text-zinc-300"><Loader2 className="h-4 w-4 animate-spin" />Loading your mapped repository…</div>;
  }

  if (error || !workspace) {
    return (
      <section className="space-y-4 rounded-xl border border-zinc-800 bg-zinc-900 p-6">
        <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm text-cyan-300 hover:text-cyan-200"><ArrowLeft className="h-4 w-4" />Dashboard</Link>
        <h1 className="text-lg font-semibold">Student Repository Workspace</h1>
        {error && <p role="alert" className="rounded border border-rose-800 bg-rose-950/30 p-3 text-sm text-rose-300">{error}</p>}
        <Button type="button" onClick={() => { setLoading(true); void loadWorkspace(); }} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />Retry</Button>
      </section>
    );
  }

  const task = {
    task_id: `student-repository-${workspace.repositoryId}`,
    title: workspace.repository,
    description: 'Edit a local draft of your mapped GitHub repository. Changes in this workspace are not written to GitHub.',
    task_type: 'repository-workspace',
    difficulty_level: 1,
    persona: 'Enterprise SaaS',
    language: workspace.language,
    starter_code: workspace.files[workspace.mainFileName] || '',
    files: workspace.files,
    main_file: workspace.mainFileName,
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-900/60 bg-cyan-950/20 p-4">
        <div>
          <Link href="/dashboard" className="mb-2 inline-flex items-center gap-2 text-xs text-cyan-300 hover:text-cyan-200"><ArrowLeft className="h-3.5 w-3.5" />Dashboard</Link>
          <h1 className="text-lg font-semibold text-zinc-100">{workspace.repository}</h1>
          <p className="mt-1 text-xs text-zinc-400">Local draft workspace · GitHub remains unchanged until a later phase.</p>
        </div>
        <Button type="button" variant="outline" onClick={() => void loadWorkspace()} disabled={loading}><RefreshCw className="mr-2 h-4 w-4" />Reload remote files</Button>
      </div>
      {workspace.skippedFiles > 0 && <p role="status" className="text-xs text-amber-300">Skipped {workspace.skippedFiles} binary or unsupported files. Workspace loading is limited to 200 text files and 10 MB.</p>}
      <p className="rounded border border-amber-900/60 bg-amber-950/20 p-3 text-xs text-amber-200">
        Run Code executes one file through Piston. Run Project uses an isolated Docker runtime for supported Python or Node projects. For web apps, Open Preview is available after startup when the framework and preview proxy are configured; dependency downloads require the approved restricted proxy.
      </p>
      <p className="text-[11px] text-zinc-500">Only repository files already loaded from GitHub can be edited in this phase; creating new files is not enabled.</p>
      <TaskEditor
        task={task}
        userId={userId}
        initialSubmission={null}
        repositoryWorkspace={{ repositoryId: workspace.repositoryId, fullName: workspace.repository, mainFileName: workspace.mainFileName }}
      />
    </div>
  );
}
