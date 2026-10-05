import { useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  ArrowUpDown,
  CheckCircle2,
  Database,
  Download,
  FileSpreadsheet,
  Info,
  Layers,
  Loader2,
  Play,
  Upload,
  X,
} from 'lucide-react'
import clsx from 'clsx'

import { ApiError, predictApi } from '@/api'
import { useWorkspace } from '@/lib/store'
import { CONFIDENCE_META, pct } from '@/lib/format'
import { EmptyState, LoadingBlock, Panel, PanelHeader, StatCard } from '@/components/ui'
import { useToast } from '@/components/Toast'
import type { Disease, DiseaseInfo, FeatureSpec } from '@/types'

const MAX_ROWS = 500

interface ParsedRow {
  index: number
  caseLabel: string | null
  values: Record<string, number>
  /** Present only for rows loaded from the public dataset. */
  trueLabel?: number
}

interface BatchRow {
  row: number
  verdict: string
  verdict_label: string
  positive_prob: number
  confidence_band: keyof typeof CONFIDENCE_META
}

interface BatchResult {
  disease: string
  model_id: string
  threshold: number
  count: number
  positives: number
  negatives: number
  mean_positive_prob: number
  results: BatchRow[]
}

/* -------------------------------------------------------------------------- */
/* CSV parsing                                                                */
/* -------------------------------------------------------------------------- */

/** Minimal RFC4180-ish reader: handles quoted fields, escaped quotes, CRLF. */
function splitCsvLine(line: string): string[] {
  const out: string[] = []
  let field = ''
  let quoted = false

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (quoted) {
      if (ch === '"') {
        if (line[i + 1] === '"') {
          field += '"'
          i += 1
        } else {
          quoted = false
        }
      } else {
        field += ch
      }
    } else if (ch === '"') {
      quoted = true
    } else if (ch === ',') {
      out.push(field)
      field = ''
    } else {
      field += ch
    }
  }
  out.push(field)
  return out.map((f) => f.trim())
}

/**
 * Map a header cell onto a feature key.
 *
 * Accepts the native model name (`radius1`), the Chinese display name
 * (`均值半径`), or the English display name. Real reports are labelled in
 * Chinese, so requiring the raw column names would make the feature unusable
 * for anyone exporting from the UI.
 */
function resolveColumn(
  header: string,
  schema: FeatureSpec[],
): string | 'case_label' | null {
  const norm = (s: string) => s.toLowerCase().replace(/\s|_|-/g, '')
  const h = norm(header)
  if (!h) return null
  if (['caselabel', 'label', 'name', 'sample', '样本', '编号', '样本编号'].includes(h)) {
    return 'case_label'
  }
  for (const spec of schema) {
    if (
      norm(spec.key) === h ||
      norm(spec.name_zh) === h ||
      norm(spec.name_en) === h
    ) {
      return spec.key
    }
  }
  return null
}

interface ParseOutcome {
  rows: ParsedRow[]
  errors: string[]
  unmapped: string[]
}

function parseCsv(text: string, info: DiseaseInfo): ParseOutcome {
  const schema = info.feature_schema
  const errors: string[] = []
  const unmapped: string[] = []

  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
  if (!lines.length) return { rows: [], errors: ['没有可解析的内容'], unmapped }

  const firstCells = splitCsvLine(lines[0])
  const looksNumeric = firstCells.every((c) => c !== '' && Number.isFinite(Number(c)))

  let keys: (string | 'case_label' | null)[] = []
  let dataLines = lines

  if (looksNumeric) {
    // No header: fall back to schema order, which is how the model reads input.
    if (firstCells.length !== schema.length) {
      return {
        rows: [],
        errors: [
          `没有表头，且首行有 ${firstCells.length} 列，与 ${info.display_zh} 需要的 ${schema.length} 个特征不匹配。` +
            '请补上表头，或按模型特征顺序提供完整列。',
        ],
        unmapped,
      }
    }
    keys = schema.map((s) => s.key)
  } else {
    keys = firstCells.map((c) => {
      const resolved = resolveColumn(c, schema)
      if (resolved === null) unmapped.push(c)
      return resolved
    })
    dataLines = lines.slice(1)
    const mapped = keys.filter((k) => k && k !== 'case_label').length
    if (mapped === 0) {
      return {
        rows: [],
        errors: [
          '表头里的列名没有一列能对应到模型特征。' +
            `请使用原生特征名（如 ${schema[0]?.key}）或中文名（如 ${schema[0]?.name_zh}）。`,
        ],
        unmapped,
      }
    }
  }

  const rows: ParsedRow[] = []
  dataLines.forEach((line, i) => {
    const cells = splitCsvLine(line)
    const values: Record<string, number> = {}
    let caseLabel: string | null = null

    keys.forEach((key, col) => {
      const raw = cells[col]
      if (key === null || raw === undefined || raw === '') return
      const value = Number(raw)
      if (!Number.isFinite(value)) return
      if (key === 'case_label') caseLabel = raw
      else values[key] = value
    })

    const missing = schema.filter((s) => values[s.key] === undefined)
    if (missing.length) {
      errors.push(
        `第 ${i + 1} 行缺少 ${missing.length} 个特征（例如 ${missing[0].name_zh}），已跳过`,
      )
      return
    }
    rows.push({ index: rows.length, caseLabel, values })
  })

  if (rows.length > MAX_ROWS) {
    errors.push(`共 ${rows.length} 行，超出单次上限 ${MAX_ROWS} 行，只取前 ${MAX_ROWS} 行`)
  }
  return { rows: rows.slice(0, MAX_ROWS), errors, unmapped }
}

/* -------------------------------------------------------------------------- */

export default function BatchPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const { diseases, activeDisease, setActiveDisease } = useWorkspace()
  const fileInput = useRef<HTMLInputElement>(null)

  const [mode, setMode] = useState<'upload' | 'paste' | 'demo'>('demo')
  const [pasted, setPasted] = useState('')
  const [fileName, setFileName] = useState<string | null>(null)
  const [parsed, setParsed] = useState<ParsedRow[]>([])
  const [sampleNote, setSampleNote] = useState<string | null>(null)
  const [parseErrors, setParseErrors] = useState<string[]>([])
  const [unmapped, setUnmapped] = useState<string[]>([])
  const [algorithm, setAlgorithm] = useState<string | null>(null)
  const [result, setResult] = useState<BatchResult | null>(null)
  const [sortByProb, setSortByProb] = useState(false)

  const info = diseases.find((d) => d.disease === activeDisease)

  const run = useMutation({
    mutationFn: (rows: ParsedRow[]) =>
      predictApi.batch({
        disease: activeDisease,
        model: algorithm,
        rows: rows.map((r) => r.values),
      }),
    onSuccess: (data) => {
      setResult(data as unknown as BatchResult)
      qc.invalidateQueries({ queryKey: ['records'] })
      qc.invalidateQueries({ queryKey: ['stats'] })
      toast.success(
        '批量评估完成',
        `共 ${data.count} 份样本，阳性 ${data.positives} 份、阴性 ${data.negatives} 份`,
      )
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : '请稍后重试'
      toast.error('批量评估失败', msg)
    },
  })

  const applyParse = (text: string, name: string | null) => {
    if (!info) return
    const outcome = parseCsv(text, info)
    setParseErrors(outcome.errors)
    setUnmapped(outcome.unmapped)
    setParsed(outcome.rows)
    setFileName(name)
    setSampleNote(null)
    setResult(null)
    run.reset()
  }

  const onFile = async (file: File) => {
    try {
      const text = await file.text()
      applyParse(text, file.name)
    } catch {
      toast.error('读取文件失败', '请确认文件是 UTF-8 编码的 CSV')
    }
  }

  const loadSamples = async () => {
    if (!info) return
    try {
      const set = await predictApi.samples({
        disease: activeDisease,
        n: 12,
        seed: 20261004,
        balanced: true,
      })
      setParsed(
        set.rows.map((r, i) => ({
          index: i,
          caseLabel: r.case_label,
          values: r.features,
          trueLabel: r.true_label,
        })),
      )
      setSampleNote(set.note)
      setParseErrors([])
      setUnmapped([])
      setFileName(null)
      setResult(null)
      run.reset()
    } catch (err) {
      toast.error('载入样本失败', err instanceof ApiError ? err.message : '请稍后重试')
    }
  }

  const clearAll = () => {
    setParsed([])
    setParseErrors([])
    setUnmapped([])
    setFileName(null)
    setSampleNote(null)
    setPasted('')
    setResult(null)
    run.reset()
  }

  const switchDisease = (d: Disease) => {
    setActiveDisease(d)
    clearAll()
    setAlgorithm(null)
  }

  const exportCsv = () => {
    if (!result || !info) return
    const header = [
      '序号',
      '样本标签',
      ...info.feature_schema.map((s) => s.name_zh),
      '判定',
      '阳性概率',
      '置信度',
      ...(hasLabels ? ['数据集标签', '是否一致'] : []),
    ]
    const sorted = sortByProb ? sortedResults : result.results
    const lines = [header.join(',')]
    for (const r of sorted) {
      const src = parsed[r.row]
      const truth = src?.trueLabel
      const cells = [
        String(r.row + 1),
        src?.caseLabel ?? '',
        ...info.feature_schema.map((s) => String(src?.values[s.key] ?? '')),
        r.verdict_label,
        r.positive_prob.toFixed(6),
        CONFIDENCE_META[r.confidence_band]?.label ?? r.confidence_band,
        ...(hasLabels
          ? [
              truth === undefined
                ? ''
                : truth === 1
                  ? info.positive_label_zh
                  : info.negative_label_zh,
              truth === undefined
                ? ''
                : (truth === 1) === (r.verdict === 'positive')
                  ? '一致'
                  : '不一致',
            ]
          : []),
      ]
      // Quote anything that could contain a comma.
      lines.push(cells.map((c) => (/[",\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(','))
    }
    const blob = new Blob([`\uFEFF${lines.join('\r\n')}`], {
      type: 'text/csv;charset=utf-8',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `bcdx-batch-${result.disease}-${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(url)
    toast.success('已导出 CSV', '文件包含原始特征与模型判定，可直接用于复核')
  }

  const sortedResults = useMemo(() => {
    if (!result) return []
    return sortByProb
      ? [...result.results].sort((a, b) => b.positive_prob - a.positive_prob)
      : result.results
  }, [result, sortByProb])

  /** Probability histogram so the batch distribution is visible at a glance. */
  const histogram = useMemo(() => {
    if (!result?.results.length) return []
    const bins = new Array(10).fill(0)
    for (const r of result.results) {
      const idx = Math.min(Math.floor(r.positive_prob * 10), 9)
      bins[idx] += 1
    }
    const max = Math.max(...bins)
    return bins.map((count, i) => ({ from: i / 10, count, max }))
  }, [result])

  const hasLabels = useMemo(
    () => parsed.some((r) => r.trueLabel !== undefined),
    [parsed],
  )

  /** Agreement against the dataset's own labels — only for sampled rows. */
  const agreement = useMemo(() => {
    if (!result) return null
    let total = 0
    let agreed = 0
    for (const r of result.results) {
      const truth = parsed[r.row]?.trueLabel
      if (truth === undefined) continue
      total += 1
      if ((truth === 1) === (r.verdict === 'positive')) agreed += 1
    }
    return total ? { total, agreed } : null
  }, [result, parsed])

  if (!info) {
    return (
      <Panel>
        <LoadingBlock rows={3} />
      </Panel>
    )
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-brand-400">
            Batch
          </p>
          <h1 className="mt-1.5 text-2xl font-bold tracking-tight text-ink">
            批量评估
          </h1>
          <p className="mt-1 max-w-3xl text-sm leading-relaxed text-ink-muted">
            一次给多份样本打分，适合批量复核与教学演示。批量路径只做打分、不做归因——
            逐行跑 SHAP 在几百行的规模上开销不合理，而批量场景关心的是分诊而不是解释。
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {(['breast', 'heart'] as Disease[]).map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => switchDisease(d)}
              className={clsx(
                'rounded-lg border px-2.5 py-1.5 text-2xs font-semibold transition-all',
                activeDisease === d
                  ? 'border-brand-500/50 bg-brand-500/12 text-brand-200'
                  : 'border-line-strong bg-canvas-raised/50 text-ink-faint hover:text-ink-muted',
              )}
            >
              {d === 'breast' ? '乳腺癌' : '心脏病'}
            </button>
          ))}
        </div>
      </header>

      {/* ------------------------------ input ------------------------------ */}
      <Panel>
        <PanelHeader
          title="数据输入"
          icon={Upload}
          subtitle={`${info.display_zh} · 需要 ${info.n_features} 个特征 · 单次上限 ${MAX_ROWS} 行`}
          actions={
            parsed.length > 0 ? (
              <button type="button" onClick={clearAll} className="btn-ghost">
                <X className="h-3.5 w-3.5" />
                清空
              </button>
            ) : undefined
          }
        />
        <div className="space-y-4 p-5">
          {/* mode switch */}
          <div className="flex flex-wrap gap-1.5">
            {(
              [
                ['demo', '载入数据集样本', Database],
                ['upload', '上传 CSV', Upload],
                ['paste', '粘贴 CSV', FileSpreadsheet],
              ] as const
            ).map(([key, label, Icon]) => (
              <button
                key={key}
                type="button"
                onClick={() => setMode(key)}
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-2xs font-semibold transition-all',
                  mode === key
                    ? 'border-brand-500/50 bg-brand-500/12 text-brand-200'
                    : 'border-line-strong bg-canvas-raised/50 text-ink-faint hover:text-ink-muted',
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>

          {mode === 'demo' && (
            <div className="space-y-3">
              <button
                type="button"
                onClick={() => void loadSamples()}
                className="btn-ghost"
              >
                <Database className="h-3.5 w-3.5" />
                载入 12 份真实样本
              </button>
              <p className="flex items-start gap-2 rounded-xl border border-brand-500/25 bg-brand-500/8 px-3 py-2.5 text-2xs leading-relaxed text-ink-muted">
                <Info className="mt-0.5 h-3 w-3 shrink-0 text-brand-400" />
                <span>
                  样本直接取自公开数据集
                  <span className="font-mono text-ink-faint">
                    （{info.disease === 'breast' ? 'WDBC' : 'UCI Heart'}）
                  </span>
                  ，<strong className="font-semibold text-ink">不是模拟数据</strong>，
                  并按照数据集给出的真实标签每类各取一半，因此能同时看到两种判定。
                  真实标签会在结果表中作为对照显示。使用固定随机种子，结果可复现。
                </span>
              </p>
            </div>
          )}

          {mode === 'upload' && (
            <div className="space-y-3">
              <input
                ref={fileInput}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) void onFile(file)
                  e.target.value = ''
                }}
              />
              <button
                type="button"
                onClick={() => fileInput.current?.click()}
                className="btn-ghost"
              >
                <Upload className="h-3.5 w-3.5" />
                选择 CSV 文件
              </button>
              {fileName && (
                <p className="font-mono text-2xs text-ink-faint">已读取：{fileName}</p>
              )}
            </div>
          )}

          {mode === 'paste' && (
            <div className="space-y-3">
              <textarea
                value={pasted}
                onChange={(e) => setPasted(e.target.value)}
                rows={6}
                placeholder={`首行为表头，可使用原生特征名或中文名，例如：\n${info.feature_schema
                  .slice(0, 3)
                  .map((s) => s.key)
                  .join(',')}...\n或\n${info.feature_schema
                  .slice(0, 3)
                  .map((s) => s.name_zh)
                  .join(',')}...`}
                className="field min-h-[140px] resize-y font-mono text-2xs leading-relaxed"
              />
              <button
                type="button"
                onClick={() => applyParse(pasted, null)}
                disabled={!pasted.trim()}
                className="btn-ghost"
              >
                <FileSpreadsheet className="h-3.5 w-3.5" />
                解析粘贴内容
              </button>
            </div>
          )}

          {/* column guidance */}
          <details className="rounded-xl border border-line bg-canvas/50 px-4 py-3">
            <summary className="cursor-pointer text-2xs font-semibold text-ink-muted marker:content-none">
              需要哪些列？（共 {info.n_features} 个特征，点击展开）
            </summary>
            <div className="mt-3 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
              {info.feature_schema.map((s) => (
                <div
                  key={s.key}
                  className="flex items-center justify-between gap-2 rounded-lg border border-line/60 bg-canvas/60 px-2.5 py-1.5"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-2xs text-ink-muted">
                      {s.name_zh}
                    </span>
                    <span className="block truncate font-mono text-[0.625rem] text-ink-ghost">
                      {s.key}
                    </span>
                  </span>
                  <span className="shrink-0 font-mono text-[0.625rem] text-ink-ghost">
                    {s.min} ~ {s.max}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-3 text-[0.625rem] leading-relaxed text-ink-ghost">
              另可包含一列 <span className="font-mono">case_label</span>（或
              「样本编号 / 名称」）作为自定义标签，它只用于方便你辨认行，
              不会被模型读取。没有表头时按上面列出的顺序逐列对应。
            </p>
          </details>

          {/* parse feedback */}
          {sampleNote && (
            <p className="flex items-start gap-2 rounded-xl border border-brand-500/25 bg-brand-500/8 px-3 py-2.5 text-2xs leading-relaxed text-ink-muted">
              <Info className="mt-0.5 h-3 w-3 shrink-0 text-brand-400" />
              <span>{sampleNote}</span>
            </p>
          )}

          {unmapped.length > 0 && (
            <p className="flex items-start gap-2 rounded-xl border border-line bg-canvas/60 px-3 py-2.5 text-2xs leading-relaxed text-ink-faint">
              <Info className="mt-0.5 h-3 w-3 shrink-0" />
              <span>
                以下列名无法对应到模型特征，已忽略：
                <span className="font-mono text-ink-muted">{unmapped.join('、')}</span>
              </span>
            </p>
          )}

          {parseErrors.length > 0 && (
            <div className="space-y-1.5 rounded-xl border border-risk-warn/30 bg-risk-warnSoft/25 px-3 py-2.5">
              {parseErrors.map((e, i) => (
                <p
                  key={i}
                  className="flex items-start gap-2 text-2xs leading-relaxed text-risk-warn/90"
                >
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  {e}
                </p>
              ))}
            </div>
          )}

          {/* preview + run */}
          {parsed.length > 0 && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line/60 pt-4">
                <div className="flex items-center gap-2">
                  <span className="chip-safe">
                    <CheckCircle2 className="h-3 w-3" />
                    已解析 {parsed.length} 行
                  </span>
                  <span className="text-2xs text-ink-ghost">
                    特征已全部校验通过，可直接运行
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <label className="label mb-0">模型</label>
                  <select
                    value={algorithm ?? ''}
                    onChange={(e) => setAlgorithm(e.target.value || null)}
                    className="field w-auto py-2 text-xs"
                  >
                    <option value="">默认（当前冠军模型）</option>
                    {info.models.map((m) => (
                      <option key={m.id} value={m.algorithm}>
                        {m.algorithm_zh} · AUC {m.test.roc_auc.toFixed(4)}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => run.mutate(parsed)}
                    disabled={run.isPending}
                    className="btn-primary"
                  >
                    {run.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                    开始批量评估
                  </button>
                </div>
              </div>

              <div className="overflow-x-auto scroll-area rounded-xl border border-line">
                <table className="w-full min-w-[640px] border-collapse text-2xs">
                  <thead>
                    <tr className="border-b border-line bg-canvas/50">
                      <th className="px-3 py-2 text-left font-semibold text-ink-faint">#</th>
                      <th className="px-3 py-2 text-left font-semibold text-ink-faint">
                        样本标签
                      </th>
                      {info.feature_schema.slice(0, 4).map((s) => (
                        <th
                          key={s.key}
                          className="px-3 py-2 text-right font-semibold text-ink-faint"
                        >
                          {s.name_zh}
                        </th>
                      ))}
                      <th className="px-3 py-2 text-left font-semibold text-ink-ghost">
                        其余 {info.n_features - 4} 项
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {parsed.slice(0, 8).map((r) => (
                      <tr key={r.index} className="border-b border-line/50">
                        <td className="px-3 py-1.5 font-mono text-ink-ghost">
                          {r.index + 1}
                        </td>
                        <td className="px-3 py-1.5 text-ink-muted">
                          {r.caseLabel ?? '—'}
                        </td>
                        {info.feature_schema.slice(0, 4).map((s) => (
                          <td
                            key={s.key}
                            className="px-3 py-1.5 text-right font-mono text-ink-muted"
                          >
                            {r.values[s.key]}
                          </td>
                        ))}
                        <td className="px-3 py-1.5 text-ink-ghost">…</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {parsed.length > 8 && (
                  <p className="border-t border-line/50 px-3 py-2 text-[0.625rem] text-ink-ghost">
                    仅预览前 8 行，实际会评估全部 {parsed.length} 行
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      </Panel>

      {/* ----------------------------- results ----------------------------- */}
      {run.isPending && (
        <Panel>
          <LoadingBlock rows={4} />
        </Panel>
      )}

      {result && !run.isPending && (
        <>
          <div
            className={clsx(
              'grid gap-4 sm:grid-cols-2',
              agreement ? 'lg:grid-cols-5' : 'lg:grid-cols-4',
            )}
          >
            <StatCard label="样本总数" value={result.count} icon={Layers} />
            <StatCard
              label="判为阳性"
              value={result.positives}
              tone="risk"
              hint={`阳性率 ${pct(result.positives / Math.max(result.count, 1), 1)}`}
            />
            <StatCard
              label="判为阴性"
              value={result.negatives}
              tone="safe"
              hint={`阴性率 ${pct(result.negatives / Math.max(result.count, 1), 1)}`}
            />
            <StatCard
              label="平均阳性概率"
              value={pct(result.mean_positive_prob, 2)}
              hint={`判定阈值 ${result.threshold.toFixed(4)}`}
            />
            {agreement && (
              <StatCard
                label="与数据集标签一致"
                value={`${agreement.agreed}/${agreement.total}`}
                tone={agreement.agreed === agreement.total ? 'safe' : 'warn'}
                hint="对照公开数据集给出的真实标签，仅供参考"
              />
            )}
          </div>

          <Panel className="overflow-hidden">
            <PanelHeader
              title="概率分布"
              icon={Layers}
              subtitle={`模型 ${result.model_id} · 判定阈值 ${result.threshold.toFixed(4)}（深色柱表示判定为阳性的区间）`}
              actions={
                <button type="button" onClick={exportCsv} className="btn-ghost">
                  <Download className="h-3.5 w-3.5" />
                  导出 CSV
                </button>
              }
            />
            <div className="p-5">
              <div className="flex items-end gap-1.5" style={{ height: 120 }}>
                {histogram.map((bin) => {
                  const isPositive = bin.from >= Math.floor(result.threshold * 10) / 10
                  return (
                    <div key={bin.from} className="flex flex-1 flex-col items-center gap-1.5">
                      <span className="font-mono text-[0.625rem] text-ink-ghost">
                        {bin.count || ''}
                      </span>
                      <div
                        className={clsx(
                          'w-full rounded-t transition-all',
                          isPositive ? 'bg-risk-high/70' : 'bg-brand-500/50',
                        )}
                        style={{
                          height: bin.max ? `${(bin.count / bin.max) * 84}px` : '2px',
                          minHeight: bin.count ? 4 : 2,
                        }}
                      />
                      <span className="font-mono text-[0.625rem] text-ink-ghost">
                        {bin.from.toFixed(1)}
                      </span>
                    </div>
                  )
                })}
              </div>
              <p className="mt-3 text-[0.625rem] leading-relaxed text-ink-ghost">
                区间按 [0,1) 等分为十档，柱顶数字为该区间内的样本数。
                阈值不是 0.5，所以「概率不到一半但判为阳性」是预期行为——
                本模型的阈值经约登指数优化，偏向筛查灵敏度，宁可多提示复查也不漏诊。
              </p>
            </div>
          </Panel>

          <Panel className="overflow-hidden">
            <PanelHeader
              title="逐行结果"
              icon={FileSpreadsheet}
              subtitle={`共 ${result.count} 行 · 阳性 ${result.positives} · 阴性 ${result.negatives}`}
              actions={
                <button
                  type="button"
                  onClick={() => setSortByProb((v) => !v)}
                  className="btn-ghost"
                >
                  <ArrowUpDown className="h-3.5 w-3.5" />
                  {sortByProb ? '按原始顺序' : '按概率排序'}
                </button>
              }
            />
            <div className="max-h-[520px] overflow-auto scroll-area">
              <table className="w-full min-w-[560px] border-collapse text-xs">
                <thead className="sticky top-0 z-10 bg-canvas-soft/95 backdrop-blur">
                  <tr className="border-b border-line">
                    <th className="px-4 py-2.5 text-left font-semibold text-ink-faint">#</th>
                    <th className="px-4 py-2.5 text-left font-semibold text-ink-faint">
                      样本标签
                    </th>
                    {hasLabels && (
                      <th className="px-4 py-2.5 text-left font-semibold text-ink-faint">
                        数据集标签
                      </th>
                    )}
                    <th className="px-4 py-2.5 text-left font-semibold text-ink-faint">
                      判定
                    </th>
                    <th className="px-4 py-2.5 text-right font-semibold text-ink-faint">
                      阳性概率
                    </th>
                    <th className="px-4 py-2.5 text-left font-semibold text-ink-faint">
                      置信度
                    </th>
                    {hasLabels && (
                      <th className="px-4 py-2.5 text-left font-semibold text-ink-faint">
                        是否一致
                      </th>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {sortedResults.map((r) => {
                    const meta = CONFIDENCE_META[r.confidence_band]
                    const positive = r.verdict === 'positive'
                    const truth = parsed[r.row]?.trueLabel
                    const agrees =
                      truth === undefined ? null : (truth === 1) === positive
                    return (
                      <tr
                        key={r.row}
                        className="border-b border-line/50 hover:bg-canvas-hover/40"
                      >
                        <td className="px-4 py-2 font-mono text-ink-ghost">{r.row + 1}</td>
                        <td className="px-4 py-2 text-ink-muted">
                          {parsed[r.row]?.caseLabel ?? '—'}
                        </td>
                        {hasLabels && (
                          <td className="px-4 py-2 text-ink-faint">
                            {truth === undefined
                              ? '—'
                              : truth === 1
                                ? info.positive_label_zh
                                : info.negative_label_zh}
                          </td>
                        )}
                        <td className="px-4 py-2">
                          <span className={positive ? 'chip-risk' : 'chip-safe'}>
                            {r.verdict_label}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right font-mono tabular-nums text-ink">
                          {pct(r.positive_prob, 2)}
                        </td>
                        <td className="px-4 py-2">
                          <span className={meta?.cls ?? 'chip-neutral'}>
                            {meta?.label ?? r.confidence_band}
                          </span>
                        </td>
                        {hasLabels && (
                          <td className="px-4 py-2">
                            {agrees === null ? (
                              <span className="text-ink-ghost">—</span>
                            ) : agrees ? (
                              <span className="inline-flex items-center gap-1 text-risk-low">
                                <CheckCircle2 className="h-3.5 w-3.5" />
                                一致
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-risk-warn">
                                <AlertTriangle className="h-3.5 w-3.5" />
                                不一致
                              </span>
                            )}
                          </td>
                        )}
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel>
            <p className="flex items-start gap-2 px-5 py-4 text-2xs leading-relaxed text-risk-warn/90">
              <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
              <span>
                批量结果同样只是统计风险估计，反映群体规律而非个体结论，
                不能作为诊断依据。批量打分不保存到历史记录（除单条评估外），
                如需留存请先导出 CSV。
              </span>
            </p>
          </Panel>
        </>
      )}

      {!parsed.length && !result && (
        <Panel>
          <EmptyState
            icon={Layers}
            title="还没有待评估的数据"
            description="载入公开数据集的真实样本、上传 CSV，或直接粘贴表格内容，然后点击开始批量评估。"
            action={
              <button type="button" onClick={() => void loadSamples()} className="btn-primary">
                <Database className="h-4 w-4" />
                载入真实样本
              </button>
            }
          />
        </Panel>
      )}
    </div>
  )
}
