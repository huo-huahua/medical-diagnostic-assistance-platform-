import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import AppShell from '@/components/AppShell'
import ErrorBoundary from '@/components/ErrorBoundary'
import { ToastProvider } from '@/components/Toast'
import { useAuth } from '@/lib/store'
import LoginPage from '@/features/auth/LoginPage'
import DashboardPage from '@/features/dashboard/DashboardPage'
import DiagnosisPage from '@/features/diagnosis/DiagnosisPage'
import BatchPage from '@/features/batch/BatchPage'
import ExplainPage from '@/features/explain/ExplainPage'
import AssistantPage from '@/features/assistant/AssistantPage'
import ComparePage from '@/features/compare/ComparePage'
import QaComparePage from '@/features/qaCompare/QaComparePage'
import RecordsPage from '@/features/records/RecordsPage'
import '@/styles/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
  },
})

function BootGate({ children }: { children: React.ReactNode }) {
  const { status, bootstrap } = useAuth()
  const [ready, setReady] = React.useState(false)

  React.useEffect(() => {
    bootstrap().finally(() => setReady(true))
    // bootstrap is stable from the zustand store
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (!ready || status === 'loading' || status === 'idle') {
    return (
      <div className="grid h-full place-items-center">
        <div className="flex flex-col items-center gap-4">
          <div className="relative grid h-12 w-12 place-items-center">
            <span className="absolute inset-0 animate-pulse-ring rounded-2xl bg-brand-500/30" />
            <span className="grid h-12 w-12 place-items-center rounded-2xl bg-gradient-to-br from-brand-400 to-brand-700">
              <svg viewBox="0 0 24 24" className="h-5 w-5 text-white" fill="none">
                <path
                  d="M3 12h4l2-5 3 10 2.5-6 1.5 3h5"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          </div>
          <p className="text-xs text-ink-faint">正在初始化平台…</p>
        </div>
      </div>
    )
  }

  return <>{children}</>
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          {/* Outermost net: catches a failure in boot, routing or the shell
              itself. Per-page failures are caught further in, by the boundary
              AppShell puts around its outlet, so that the navigation survives
              them — see `components/ErrorBoundary.tsx`. */}
          <ErrorBoundary
            label="应用外壳"
            onReset={() => {
              void queryClient.resetQueries().catch(() => {})
            }}
          >
            <BootGate>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route element={<AppShell />}>
                  <Route path="/dashboard" element={<DashboardPage />} />
                  <Route path="/diagnosis" element={<DiagnosisPage />} />
                  <Route path="/explain" element={<ExplainPage />} />
                  <Route path="/assistant" element={<AssistantPage />} />
                  <Route path="/qa-compare" element={<QaComparePage />} />
                  <Route path="/batch" element={<BatchPage />} />
                  <Route path="/compare" element={<ComparePage />} />
                  <Route path="/records" element={<RecordsPage />} />
                </Route>
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Routes>
            </BootGate>
          </ErrorBoundary>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
