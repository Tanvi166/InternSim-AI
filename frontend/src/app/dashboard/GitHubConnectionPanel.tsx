'use client';

import { useState, useEffect, useCallback } from 'react';
import { createClient } from '@/utils/supabase/client';
import Link from 'next/link';
import { toast } from 'sonner';
import {
  GitBranch,
  GitPullRequest,
  CheckCircle2,
  ExternalLink,
  Loader2,
  FolderGit2,
  Unlink,
  ShieldCheck,
  RefreshCw,
  Folder,
  ChevronRight,
  ArrowUp,
  FileCode2
} from 'lucide-react';
import { Button } from '@/components/ui/button';

interface Repository {
  id: number;
  name: string;
  full_name: string;
  owner: string;
  private: boolean;
  default_branch: string;
  html_url: string;
  description?: string;
}

interface GitHubStatus {
  connected: boolean;
  github_username?: string;
  avatar_url?: string;
  scope?: string;
  connected_at?: string;
}

interface StudentFork {
  owner: string;
  name: string;
  full_name: string;
  url: string;
  status: 'pending' | 'ready';
}

interface StudentProjectFileItem {
  name: string;
  path: string;
  type: 'directory' | 'file';
  size: number | null;
}

interface StudentProjectFileListing {
  repository: string;
  path: string;
  page: number;
  page_size: number;
  total: number;
  has_more: boolean;
  next_page: number | null;
  items: StudentProjectFileItem[];
}

interface StudentProjectTextFile {
  repository: string;
  path: string;
  size: number;
  content: string;
}

export default function GitHubConnectionPanel() {
  const [status, setStatus] = useState<GitHubStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [repositoriesError, setRepositoriesError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingRepos, setLoadingRepos] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [showRepos, setShowRepos] = useState(false);
  const [selectedRepository, setSelectedRepository] = useState<Repository | null>(null);
  const [branchName, setBranchName] = useState('feature/');
  const [creatingBranch, setCreatingBranch] = useState(false);
  const [studentFork, setStudentFork] = useState<StudentFork | null>(null);
  const [creatingFork, setCreatingFork] = useState(false);
  const [checkingFork, setCheckingFork] = useState(false);
  const [showProjectFiles, setShowProjectFiles] = useState(false);
  const [projectPath, setProjectPath] = useState('');
  const [projectFileListing, setProjectFileListing] = useState<StudentProjectFileListing | null>(null);
  const [projectFilesError, setProjectFilesError] = useState<string | null>(null);
  const [loadingProjectFiles, setLoadingProjectFiles] = useState(false);
  const [selectedProjectFile, setSelectedProjectFile] = useState<StudentProjectTextFile | null>(null);
  const [loadingProjectFile, setLoadingProjectFile] = useState(false);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

  const getAuthToken = useCallback(async () => {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token;
  }, []);

  const fetchStudentFork = useCallback(async () => {
    try {
      setCheckingFork(true);
      const token = await getAuthToken();
      if (!token) return;
      const res = await fetch(`${apiUrl}/api/github/starter-project/fork`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.status === 404) {
        setStudentFork(null);
        return;
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Could not check your project copy.');
      }
      setStudentFork(await res.json());
    } catch (err: unknown) {
      toast.error('Project copy status unavailable', {
        description: err instanceof Error ? err.message : 'Please try again.'
      });
    } finally {
      setCheckingFork(false);
    }
  }, [apiUrl, getAuthToken]);

  const fetchStatus = useCallback(async () => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
      setStatusError('GitHub status check timed out. Check the backend connection and try again.');
      setLoading(false);
    }, 20_000);
    try {
      setLoading(true);
      setStatusError(null);
      const token = await getAuthToken();
      if (controller.signal.aborted) return;
      if (!token) throw new Error('Your sign-in session is unavailable. Sign in again and retry.');

      const res = await fetch(`${apiUrl}/api/github/status`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Could not check your GitHub connection.');
      }
      const data: GitHubStatus = await res.json();
      setStatus(data);
      if (data.connected) void fetchStudentFork();
      else setStudentFork(null);
    } catch (err) {
      setStatusError(controller.signal.aborted
        ? 'GitHub status check timed out. Check the backend connection and try again.'
        : err instanceof Error ? err.message : 'Could not check your GitHub connection.');
    } finally {
      window.clearTimeout(timeoutId);
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [apiUrl, fetchStudentFork, getAuthToken]);

  const fetchRepositories = async () => {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => {
      controller.abort();
      setRepositoriesError('Repository loading timed out. Check the backend and GitHub connection, then retry.');
      setLoadingRepos(false);
    }, 20_000);
    try {
      setLoadingRepos(true);
      setRepositoriesError(null);
      setShowRepos(true);
      const token = await getAuthToken();
      if (controller.signal.aborted) return;
      if (!token) throw new Error('Your sign-in session is unavailable. Sign in again and retry.');

      const res = await fetch(`${apiUrl}/api/github/repositories`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Could not load authorized repositories.');
      }
      const data: Repository[] = await res.json();
      setRepositories(data);
      setSelectedRepository((selected) => selected ? data.find((repo) => repo.id === selected.id) ?? null : null);
    } catch (err) {
      setRepositoriesError(controller.signal.aborted
        ? 'Repository loading timed out. Check the backend and GitHub connection, then retry.'
        : err instanceof Error ? err.message : 'Could not load authorized repositories.');
    } finally {
      window.clearTimeout(timeoutId);
      if (!controller.signal.aborted) setLoadingRepos(false);
    }
  };

  const handleConnect = async () => {
    try {
      setActionLoading(true);
      const token = await getAuthToken();
      if (!token) {
        toast.error('Authentication Required', { description: 'Please sign in to link GitHub.' });
        return;
      }

      const redirectUri = `${window.location.origin}/github?github_callback=true`;
      const res = await fetch(`${apiUrl}/api/github/auth-url?redirect_uri=${encodeURIComponent(redirectUri)}`, {
        headers: { Authorization: `Bearer ${token}` }
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Could not initialize GitHub OAuth');
      }

      const { authorization_url, state } = await res.json();
      // Store state in sessionStorage to guard against client tampering
      sessionStorage.setItem('internsim_github_oauth_state', state);

      // Redirect user to GitHub
      window.location.href = authorization_url;
    } catch (err: unknown) {
      toast.error('Connection Failed', { description: err instanceof Error ? err.message : 'Could not connect GitHub.' });
      setActionLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm('Are you sure you want to disconnect your GitHub account?')) return;

    try {
      setActionLoading(true);
      const token = await getAuthToken();
      if (!token) return;

      const res = await fetch(`${apiUrl}/api/github/disconnect`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      });

      if (res.ok) {
        const result = await res.json();
        if (result.local_deleted && result.upstream_revoked) {
          toast.success('GitHub Disconnected', { description: 'Local credentials were removed and GitHub access was revoked.' });
        } else if (result.local_deleted) {
          toast.warning('Local credentials removed', {
            description: 'GitHub access may remain active. Revoke the authorization in your GitHub settings.'
          });
        } else {
          toast.error('Local disconnect incomplete', {
            description: result.upstream_revoked
              ? 'Local credentials could not be removed, but GitHub access was revoked.'
              : 'Local credentials could not be removed and GitHub access may remain active. Revoke it in GitHub settings.'
          });
          return;
        }
        setStatus({ connected: false });
        setRepositories([]);
        setSelectedRepository(null);
        setShowRepos(false);
        setStudentFork(null);
        setShowProjectFiles(false);
        setProjectFileListing(null);
        setSelectedProjectFile(null);
      } else {
        toast.error('Disconnect failed');
      }
    } catch (err: unknown) {
      toast.error('Error', { description: err instanceof Error ? err.message : 'Could not disconnect GitHub.' });
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateBranch = async () => {
    const repository = selectedRepository;
    const requestedBranch = branchName.trim();
    if (!repository || creatingBranch || !requestedBranch) return;

    try {
      setCreatingBranch(true);
      const token = await getAuthToken();
      if (!token) {
        toast.error('Authentication required', { description: 'Please sign in again to create a branch.' });
        return;
      }

      const res = await fetch(`${apiUrl}/api/github/repositories/branches`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          owner: repository.owner,
          repository: repository.name,
          branch_name: requestedBranch
        })
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error('Branch creation failed', {
          description: err.detail || 'Could not create the branch. Please check the name and try again.'
        });
        return;
      }

      const result: { branch_name: string; base_branch: string } = await res.json();
      toast.success('Feature branch created', {
        description: `${repository.full_name}:${result.branch_name} was created from ${result.base_branch}.`
      });
      setBranchName('feature/');
    } catch {
      toast.error('Branch creation failed', { description: 'Could not reach the server. Please try again.' });
    } finally {
      setCreatingBranch(false);
    }
  };

  const handleCreateStudentFork = async () => {
    if (creatingFork) return;
    try {
      setCreatingFork(true);
      const token = await getAuthToken();
      if (!token) {
        toast.error('Authentication required', { description: 'Please sign in again to create your project copy.' });
        return;
      }
      const res = await fetch(`${apiUrl}/api/github/starter-project/fork`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        toast.error('Could not create project copy', {
          description: err.detail || 'Please try again later.'
        });
        return;
      }
      const fork: StudentFork = await res.json();
      setStudentFork(fork);
      if (fork.status === 'ready') {
        toast.success('Your project copy is ready', { description: fork.full_name });
      } else {
        toast.info('Fork is being prepared', {
          description: 'GitHub is still creating the repository. Check its status in a moment.'
        });
      }
    } catch {
      toast.error('Could not create project copy', { description: 'Could not reach the server. Please try again.' });
    } finally {
      setCreatingFork(false);
    }
  };

  const loadStudentProjectFiles = async (path: string, page = 1, append = false) => {
    if (!append) setSelectedProjectFile(null);
    try {
      setLoadingProjectFiles(true);
      setProjectFilesError(null);
      const token = await getAuthToken();
      if (!token) {
        setProjectFilesError('Authentication required. Please sign in again.');
        return;
      }
      const query = new URLSearchParams({ path, page: String(page), page_size: '100' });
      const res = await fetch(`${apiUrl}/api/github/student-project/files?${query.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Could not load project files.');
      }
      const listing: StudentProjectFileListing = await res.json();
      setProjectPath(listing.path);
      setProjectFileListing((current) => append && current
        ? { ...listing, items: [...current.items, ...listing.items] }
        : listing);
    } catch (err) {
      setProjectFilesError(err instanceof Error ? err.message : 'Could not load project files.');
    } finally {
      setLoadingProjectFiles(false);
    }
  };

  const openStudentProject = () => {
    if (studentFork?.status !== 'ready') return;
    setShowProjectFiles(true);
    setProjectPath('');
    setProjectFileListing(null);
    setSelectedProjectFile(null);
    void loadStudentProjectFiles('');
  };

  const openStudentProjectFile = async (path: string) => {
    try {
      setLoadingProjectFile(true);
      setProjectFilesError(null);
      const token = await getAuthToken();
      if (!token) {
        setProjectFilesError('Authentication required. Please sign in again.');
        return;
      }
      const query = new URLSearchParams({ path });
      const res = await fetch(`${apiUrl}/api/github/student-project/file?${query.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Could not open this file.');
      }
      setSelectedProjectFile(await res.json());
    } catch (err) {
      setProjectFilesError(err instanceof Error ? err.message : 'Could not open this file.');
    } finally {
      setLoadingProjectFile(false);
    }
  };

  // Check URL params for callback after GitHub redirect
  useEffect(() => {
    const handleCallback = async () => {
      const urlParams = new URLSearchParams(window.location.search);
      const code = urlParams.get('code');
      const state = urlParams.get('state');

      if (code && state) {
        const storedState = sessionStorage.getItem('internsim_github_oauth_state');
        if (storedState && storedState !== state) {
          toast.error('Security Check Failed', { description: 'OAuth state mismatch detected.' });
          return;
        }

        try {
          setActionLoading(true);
          const token = await getAuthToken();
          if (!token) return;

          const redirectUri = `${window.location.origin}/github?github_callback=true`;
          const res = await fetch(`${apiUrl}/api/github/exchange-code`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${token}`
            },
            body: JSON.stringify({ code, state, redirect_uri: redirectUri })
          });

          if (res.ok) {
            const data = await res.json();
            setStatus(data);
            if (data.connected) void fetchStudentFork();
            toast.success('GitHub Connected Successfully!', {
              description: `Linked as @${data.github_username}`
            });
            // Clean URL query params
            window.history.replaceState({}, document.title, window.location.pathname);
            sessionStorage.removeItem('internsim_github_oauth_state');
          } else {
            const err = await res.json().catch(() => ({}));
            toast.error('Connection Failed', { description: err.detail || 'Code exchange error.' });
          }
        } catch (err: unknown) {
          toast.error('OAuth Exchange Failed', { description: err instanceof Error ? err.message : 'Could not finish the GitHub connection.' });
        } finally {
          setActionLoading(false);
        }
      }
    };

    void Promise.resolve().then(() => {
      const callbackParams = new URLSearchParams(window.location.search);
      if (callbackParams.has('code') && callbackParams.has('state')) {
        return handleCallback().finally(() => { void fetchStatus(); });
      }
      return fetchStatus();
    });
  }, [apiUrl, fetchStatus, fetchStudentFork, getAuthToken]);

  if (loading) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 font-mono text-xs flex items-center justify-between text-zinc-400">
        <div className="flex items-center gap-2">
          <GitPullRequest className="h-4 w-4 animate-pulse text-zinc-500" />
          <span>Checking GitHub integration status...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/70 backdrop-blur-md p-5 space-y-4 font-mono text-xs shadow-lg">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-zinc-800/80 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="h-7 w-7 rounded-lg bg-zinc-950 border border-zinc-800 flex items-center justify-center text-zinc-200">
            <GitPullRequest className="h-4 w-4 text-cyan-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-zinc-100 font-sans text-sm">GitHub Workspace Integration</span>
              {status?.connected && (
                <span className="px-2 py-0.5 rounded-full bg-emerald-950/80 text-emerald-400 border border-emerald-800/60 text-[10px] font-semibold flex items-center gap-1">
                  <CheckCircle2 className="h-2.5 w-2.5" />
                  Connected
                </span>
              )}
            </div>
            <p className="text-[11px] text-zinc-400 font-sans mt-0.5">
              Link your GitHub account to browse and select an authorized repository.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {status?.connected ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={fetchRepositories}
                disabled={loadingRepos}
                className="h-8 text-xs font-mono border-zinc-800 bg-zinc-950/60 hover:bg-zinc-800 text-zinc-300"
              >
                {loadingRepos ? (
                  <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
                ) : (
                  <FolderGit2 className="h-3 w-3 mr-1.5 text-cyan-400" />
                )}
                <span>Browse Repos</span>
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDisconnect}
                disabled={actionLoading}
                className="h-8 text-xs font-mono text-rose-400 hover:text-rose-300 hover:bg-rose-950/40"
              >
                <Unlink className="h-3 w-3 mr-1.5" />
                <span>Disconnect</span>
              </Button>
            </>
          ) : statusError ? (
            <Button variant="outline" size="sm" onClick={fetchStatus} disabled={loading} className="h-8 text-xs">
              {loading ? <Loader2 className="mr-1.5 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1.5 h-3 w-3" />}
              Retry connection check
            </Button>
          ) : (
            <Button
              size="sm"
              onClick={handleConnect}
              disabled={actionLoading}
              className="h-8 text-xs font-mono bg-cyan-600 hover:bg-cyan-500 text-black font-semibold shadow-md shadow-cyan-900/20"
            >
              {actionLoading ? (
                <Loader2 className="h-3 w-3 animate-spin mr-1.5" />
              ) : (
                <GitPullRequest className="h-3.5 w-3.5 mr-1.5" />
              )}
              <span>Connect GitHub</span>
            </Button>
          )}
        </div>
      </div>

      {statusError && <div role="alert" className="flex flex-col gap-2 rounded-lg border border-rose-900/70 bg-rose-950/20 p-3 text-[11px] text-rose-200 sm:flex-row sm:items-center sm:justify-between"><span>{statusError}</span><span className="text-rose-300/70">Connection status could not be verified.</span></div>}

      {status?.connected && (
        <div className="flex items-center justify-between text-zinc-400 bg-zinc-950/40 p-3 rounded-lg border border-zinc-800/60 text-[11px]">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-3.5 w-3.5 text-cyan-400 shrink-0" />
            <span>
              Connected as <strong className="text-zinc-200">@{status.github_username}</strong>
            </span>
          </div>
          <span className="text-[10px] text-zinc-400">Tokens encrypted at rest (AES-256-GCM)</span>
        </div>
      )}

      {status?.connected && (
        <section aria-labelledby="starter-project-heading" className="rounded-lg border border-violet-800/60 bg-violet-950/20 p-3 space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <h3 id="starter-project-heading" className="text-xs font-semibold text-violet-200">Platform starter</h3>
              <p className="mt-1 text-[11px] text-zinc-300">
                Source: <a className="underline hover:text-white" href="https://github.com/Tanvi166/trendhive" target="_blank" rel="noopener noreferrer">Tanvi166/trendhive</a>
                <span className="text-zinc-500"> · unchanged by this action</span>
              </p>
            </div>
            {!studentFork && (
              <Button
                type="button"
                onClick={handleCreateStudentFork}
                disabled={creatingFork || checkingFork}
                className="h-9 text-xs font-mono bg-violet-600 hover:bg-violet-500 text-white font-semibold disabled:opacity-50"
              >
                {creatingFork ? <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin mr-1.5" /> : <FolderGit2 aria-hidden="true" className="h-3 w-3 mr-1.5" />}
                {creatingFork ? 'Creating your copy…' : checkingFork ? 'Checking your copy…' : 'Create My Project Copy'}
              </Button>
            )}
          </div>

          {studentFork ? (
            <div className="rounded-md border border-zinc-700 bg-zinc-950/70 p-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-zinc-500">Your working repository</p>
                  <a href={studentFork.url} target="_blank" rel="noopener noreferrer" className="text-xs font-semibold text-cyan-300 underline hover:text-cyan-200">
                    {studentFork.full_name} <ExternalLink aria-hidden="true" className="inline h-3 w-3" />
                  </a>
                </div>
                <span className={`rounded-full border px-2 py-1 text-[10px] ${studentFork.status === 'ready' ? 'border-emerald-800 bg-emerald-950/60 text-emerald-300' : 'border-amber-800 bg-amber-950/60 text-amber-300'}`}>
                  {studentFork.status === 'ready' ? 'Ready' : 'Fork pending'}
                </span>
              </div>
              {studentFork.status === 'pending' && (
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-[11px] text-zinc-400">
                  <span>GitHub is still preparing the fork. Your starter source remains separate.</span>
                  <Button type="button" variant="outline" size="sm" onClick={fetchStudentFork} disabled={checkingFork} className="h-8 text-[10px]">
                    {checkingFork ? <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin mr-1" /> : <RefreshCw aria-hidden="true" className="h-3 w-3 mr-1" />}
                    Check status
                  </Button>
                </div>
              )}
              {studentFork.status === 'ready' && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    onClick={openStudentProject}
                    disabled={loadingProjectFiles}
                    className="h-8 text-xs bg-cyan-800 hover:bg-cyan-700 text-white"
                  >
                    {loadingProjectFiles ? <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin mr-1.5" /> : <FolderGit2 aria-hidden="true" className="h-3 w-3 mr-1.5" />}
                    Browse read-only
                  </Button>
                  <Link href="/github/workspace" className="inline-flex h-8 items-center rounded-lg border border-transparent bg-cyan-600 px-3 text-xs font-medium text-black hover:bg-cyan-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400">
                    <FolderGit2 aria-hidden="true" className="h-3 w-3 mr-1.5" />Open Workspace
                  </Link>
                </div>
              )}
            </div>
          ) : (
            <p className="text-[11px] text-zinc-400">Create a separate copy in your own GitHub account to use as your working repository.</p>
          )}
        </section>
      )}

      {showProjectFiles && studentFork?.status === 'ready' && (
        <section aria-labelledby="student-project-files-heading" className="rounded-lg border border-cyan-800/60 bg-zinc-950/50 p-3 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h3 id="student-project-files-heading" className="text-xs font-semibold text-cyan-200">Read-only project browser</h3>
              <p className="mt-1 text-[11px] text-zinc-400">{projectFileListing?.repository || studentFork.full_name}</p>
            </div>
            <Button type="button" variant="outline" size="sm" onClick={() => setShowProjectFiles(false)} className="h-7 text-[10px]">Close</Button>
          </div>

          {projectFilesError && <p role="alert" className="rounded border border-rose-800/60 bg-rose-950/30 p-2 text-[11px] text-rose-300">{projectFilesError}</p>}
          {loadingProjectFiles && <p role="status" className="flex items-center gap-2 text-[11px] text-zinc-400"><Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" /> Loading repository files…</p>}

          {projectFileListing && (
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
              <div className="min-w-0 space-y-2">
                <div className="flex items-center gap-2 text-[10px] text-zinc-400">
                  {projectPath && <button type="button" onClick={() => loadStudentProjectFiles(projectPath.split('/').slice(0, -1).join('/'))} className="inline-flex items-center gap-1 underline hover:text-white"><ArrowUp aria-hidden="true" className="h-3 w-3" /> Parent</button>}
                  <span className="truncate">/{projectPath}</span>
                </div>
                {projectFileListing.items.length === 0 && !loadingProjectFiles ? <p className="text-[11px] text-zinc-500">This folder is empty.</p> : (
                  <ul className="max-h-72 space-y-1 overflow-y-auto" aria-label="Repository files">
                    {projectFileListing.items.map((item) => (
                      <li key={item.path}>
                        <button
                          type="button"
                          onClick={() => item.type === 'directory' ? loadStudentProjectFiles(item.path) : openStudentProjectFile(item.path)}
                          disabled={loadingProjectFile || loadingProjectFiles}
                          className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-[11px] hover:bg-zinc-800 disabled:opacity-50 ${selectedProjectFile?.path === item.path ? 'bg-cyan-950/50 text-cyan-200' : 'text-zinc-300'}`}
                        >
                          {item.type === 'directory' ? <Folder aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-amber-300" /> : <FileCode2 aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-cyan-400" />}
                          <span className="min-w-0 flex-1 truncate">{item.name}</span>
                          {item.type === 'directory' && <ChevronRight aria-hidden="true" className="h-3 w-3 shrink-0" />}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
                {projectFileListing.has_more && projectFileListing.next_page && (
                  <Button type="button" variant="outline" size="sm" onClick={() => loadStudentProjectFiles(projectPath, projectFileListing.next_page!, true)} disabled={loadingProjectFiles} className="h-7 text-[10px]">Load more</Button>
                )}
              </div>
              <div className="min-w-0 rounded border border-zinc-800 bg-black/40">
                {loadingProjectFile ? <p role="status" className="p-3 text-[11px] text-zinc-400">Loading file…</p> : selectedProjectFile ? (
                  <>
                    <div className="border-b border-zinc-800 px-3 py-2 text-[10px] text-zinc-400">{selectedProjectFile.path} · {selectedProjectFile.size.toLocaleString()} bytes · read-only</div>
                    <pre className="max-h-96 overflow-auto p-3 text-[11px] leading-relaxed text-zinc-200"><code>{selectedProjectFile.content}</code></pre>
                  </>
                ) : <p className="p-3 text-[11px] text-zinc-500">Select a text file to preview it. Repository contents are read-only.</p>}
              </div>
            </div>
          )}
        </section>
      )}

      {selectedRepository && (
        <div className="rounded-lg border border-cyan-800/70 bg-cyan-950/30 p-3 text-[11px] text-cyan-200 space-y-2">
          <div role="status" aria-live="polite">
            Selected repository: <strong>{selectedRepository.full_name}</strong>
          </div>
          <div className="flex flex-col sm:flex-row sm:items-end gap-2">
            <div className="flex-1 space-y-1">
              <label htmlFor="github-feature-branch" className="block text-zinc-300">Feature branch name</label>
              <input
                id="github-feature-branch"
                value={branchName}
                onChange={(event) => setBranchName(event.target.value)}
                maxLength={120}
                disabled={creatingBranch}
                placeholder="feature/my-change"
                className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-2.5 py-2 text-zinc-100 placeholder:text-zinc-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
              />
            </div>
            <Button
              type="button"
              onClick={handleCreateBranch}
              disabled={creatingBranch || !branchName.trim()}
              className="h-9 text-xs font-mono bg-cyan-600 hover:bg-cyan-500 text-black font-semibold disabled:opacity-50"
            >
              {creatingBranch ? (
                <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin mr-1.5" />
              ) : (
                <GitBranch aria-hidden="true" className="h-3 w-3 mr-1.5" />
              )}
              {creatingBranch ? 'Creating branch…' : 'Create feature branch'}
            </Button>
          </div>
        </div>
      )}

      {/* Repositories List */}
      {showRepos && (
        <div className="space-y-2 pt-2 border-t border-zinc-800/60">
          <div className="flex items-center justify-between text-xs text-zinc-400">
            <span>Authorized Repositories ({repositories.length})</span>
            <button
              onClick={() => setShowRepos(false)}
              className="text-[10px] text-zinc-400 hover:text-zinc-300 underline"
            >
              Hide
            </button>
          </div>

          {loadingRepos ? (
            <p role="status" className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950/60 p-4 text-zinc-400"><Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />Loading repositories authorized for your GitHub account…</p>
          ) : repositoriesError ? (
            <div className="flex flex-col gap-3 rounded-lg border border-rose-900/70 bg-rose-950/20 p-4 text-rose-200 sm:flex-row sm:items-center sm:justify-between">
              <p role="alert">{repositoriesError}</p>
              <Button type="button" variant="outline" size="sm" onClick={fetchRepositories} className="h-8 text-[10px]"><RefreshCw aria-hidden="true" className="mr-1.5 h-3 w-3" />Retry repositories</Button>
            </div>
          ) : repositories.length === 0 ? (
            <div className="p-4 text-center text-zinc-400 bg-zinc-950/60 rounded-lg border border-zinc-800">
              No repositories found. Ensure your GitHub account has authorized repositories.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-56 overflow-y-auto pr-1">
              {repositories.map((repo) => (
                <div
                  key={repo.id}
                  className={`rounded-lg border transition-colors flex items-center gap-2 p-2.5 ${
                    selectedRepository?.id === repo.id
                      ? 'bg-cyan-950/50 border-cyan-500/80 ring-1 ring-cyan-500/40'
                      : 'bg-zinc-950/60 border-zinc-800/80 hover:border-zinc-700'
                  }`}
                >
                  <button
                    type="button"
                    aria-pressed={selectedRepository?.id === repo.id}
                    aria-label={`Select ${repo.full_name}`}
                    onClick={() => setSelectedRepository(repo)}
                    className="min-w-0 flex-1 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
                  >
                    <div className="flex items-center gap-1.5">
                      <FolderGit2 className="h-3 w-3 text-cyan-400 shrink-0" />
                      <span className="font-semibold text-zinc-200 truncate">{repo.name}</span>
                      {repo.private && (
                        <span className="px-1 py-0.2 rounded bg-zinc-800 text-zinc-400 text-[9px]">Private</span>
                      )}
                      {selectedRepository?.id === repo.id && (
                        <CheckCircle2 aria-hidden="true" className="h-3.5 w-3.5 text-cyan-300 shrink-0 ml-auto" />
                      )}
                    </div>
                    <p className="text-[10px] text-zinc-400 truncate mt-0.5">
                      {repo.description || repo.full_name}
                    </p>
                  </button>
                  <a
                    href={repo.html_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`Open ${repo.full_name} on GitHub in a new tab`}
                    className="text-zinc-500 hover:text-zinc-300 p-1"
                  >
                    <ExternalLink aria-hidden="true" className="h-3 w-3" />
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
