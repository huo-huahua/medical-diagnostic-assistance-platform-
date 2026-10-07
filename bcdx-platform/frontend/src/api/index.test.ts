import type { AxiosError, AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, authApi, http, ragApi, setUnauthorizedHandler, tokenStore } from '@/api'

/**
 * The envelope and the error-explanation chain.
 *
 * These are the two functions every request in the app passes through, so a
 * mistake here is not a wrong message on one screen — it is a wrong message on
 * every screen. The `explain()` branch in particular is what used to collapse
 * every failure into the literal string "请求失败": the backend knew exactly
 * which field was wrong and the UI threw that away.
 */
describe('the response envelope', () => {
  afterEach(() => {
    // Leave no stub behind; each test installs its own.
    http.defaults.adapter = undefined
  })

  const ok = (data: unknown) => {
    http.defaults.adapter = async (config: InternalAxiosRequestConfig) =>
      ({
        data: { code: 0, message: 'ok', data, request_id: 'r1' },
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      }) as AxiosResponse
  }

  it('hands back `data` and nothing else', async () => {
    ok({ access_token: 't', user: { email: 'a@b.com' } })
    await expect(authApi.login({ email: 'a@b.com', password: 'secret12' })).resolves.toEqual({
      access_token: 't',
      user: { email: 'a@b.com' },
    })
  })

  it('propagates a data payload that is legitimately null', async () => {
    ok(null)
    await expect(authApi.login({ email: 'a@b.com', password: 'secret12' })).resolves.toBeNull()
  })
})

describe('explain(): how a failure becomes something a human can act on', () => {
  afterEach(() => {
    http.defaults.adapter = undefined
  })

  /** Throw an error shaped like axios would, with `status` and `data`. */
  const fail = (
    status: number,
    data: unknown,
    extra: Record<string, unknown> = {},
  ) => {
    http.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      const err = new Error(`Request failed with status code ${status}`) as AxiosError
      err.isAxiosError = true
      err.config = config
      err.response = { data, status, statusText: '', headers: {}, config } as AxiosResponse
      Object.assign(err, extra)
      throw err
    }
  }

  /** Resolves to the message the UI would show, or a sentinel if nothing threw. */
  const expectMessage = async (
    status: number,
    data: unknown,
    extra: Record<string, unknown> = {},
  ): Promise<string> => {
    fail(status, data, extra)
    const err = await authApi
      .login({ email: 'a@b.com', password: 'x' })
      .then(() => null)
      .catch((e: unknown) => e as Error)
    return err === null ? '<nothing was thrown>' : err.message
  }

  it('prefers `message`, which is what the unified envelope always sets', async () => {
    await expect(
      expectMessage(422, { code: 1001, message: 'Validation failed: password — too short' }),
    ).resolves.toBe('Validation failed: password — too short')
  })

  it('falls back to a plain-string `detail` for a backend that bypassed the envelope', async () => {
    await expect(expectMessage(500, { detail: 'database is locked' })).resolves.toBe(
      'database is locked',
    )
  })

  it('reads FastAPI’s own validation shape and names the offending field', async () => {
    // `{loc, msg}[]` is what FastAPI returns when the unified handler is *not*
    // installed — exactly the shape that produced the bare "请求失败".
    await expect(
      expectMessage(422, {
        detail: [{ loc: ['body', 'password'], msg: 'Value error, Password must mix letters' }],
      }),
    ).resolves.toBe('password: Value error, Password must mix letters')
  })

  it('drops `body` from the field path — it is how the request was sent, not what was wrong', async () => {
    await expect(
      expectMessage(422, { detail: [{ loc: ['body'], msg: 'Field required' }] }),
    ).resolves.toBe('Field required')
  })

  it('says "timeout" rather than a bare status when the call was aborted', async () => {
    await expect(expectMessage(0, undefined, { code: 'ECONNABORTED' })).resolves.toMatch(
      /请求超时/,
    )
  })

  it('says "cannot reach the backend" on a network failure', async () => {
    await expect(expectMessage(0, undefined, { message: 'Network Error' })).resolves.toMatch(
      /无法连接后端服务/,
    )
  })

  it('falls back to a status-bearing message only when nothing better exists', async () => {
    await expect(expectMessage(503, undefined)).resolves.toBe('请求失败（HTTP 503）')
  })

  it('never returns an empty string — an empty error is worse than a vague one', async () => {
    const msg = await expectMessage(500, {})
    expect(msg.length).toBeGreaterThan(0)
  })
})

describe('the error object the UI receives', () => {
  afterEach(() => {
    http.defaults.adapter = undefined
  })

  it('carries the code, status and request id so the panel can show them', async () => {
    http.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      const err = new Error('boom') as AxiosError
      err.isAxiosError = true
      err.config = config
      err.response = {
        data: { code: 1002, message: 'bad input', request_id: 'rid-9' },
        status: 422,
        statusText: '',
        headers: {},
        config,
      } as AxiosResponse
      throw err
    }
    const err = (await authApi
      .login({ email: 'a@b.com', password: 'x' })
      .catch((e: unknown) => e)) as ApiError

    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe(1002)
    expect(err.status).toBe(422)
    expect(err.requestId).toBe('rid-9')
  })
})

describe('a 401 clears the session', () => {
  afterEach(() => {
    http.defaults.adapter = undefined
  })

  it('drops the token and notifies the app so it can bounce to sign-in', async () => {
    tokenStore.set('a-token')
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)

    http.defaults.adapter = async (config: InternalAxiosRequestConfig) => {
      const err = new Error('unauthorized') as AxiosError
      err.isAxiosError = true
      err.config = config
      err.response = {
        data: { code: 2001, message: 'Authentication required' },
        status: 401,
        statusText: '',
        headers: {},
        config,
      } as AxiosResponse
      throw err
    }

    await expect(authApi.me()).rejects.toBeInstanceOf(ApiError)
    expect(tokenStore.get()).toBeNull()
    expect(onUnauthorized).toHaveBeenCalledTimes(1)

    setUnauthorizedHandler(() => {})
  })
})

describe('SSE streaming', () => {
  const stream = (chunks: string[]) =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder()
        for (const c of chunks) controller.enqueue(encoder.encode(c))
        controller.close()
      },
    })

  it('hands meta and every delta to the caller, then signals done once', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: stream([
        'event: meta\ndata: {"refused":false,"hit_count":4}\n\n',
        'event: delta\ndata: {"text":"一般风险女性"}\n\n',
        'event: delta\ndata: {"text":"建议 40 岁起筛查"}\n\n',
      ]),
    }) as unknown as typeof fetch

    const meta: unknown[] = []
    let text = ''
    let done = 0

    await ragApi.askStream(
      { question: '乳腺癌筛查多久一次？', disease: 'breast' },
      {
        onMeta: (m) => meta.push(m),
        onDelta: (t) => {
          text += t
        },
        onDone: () => {
          done += 1
        },
      },
    )

    expect(meta).toEqual([{ refused: false, hit_count: 4 }])
    expect(text).toBe('一般风险女性建议 40 岁起筛查')
    expect(done).toBe(1)
  })

  it('splits frames that arrive mid-chunk instead of dropping them', async () => {
    // A real network does not respect frame boundaries; the reader has to
    // buffer. These two chunks split a frame clean down the middle.
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      body: stream(['event: delta\ndata: {"text":"前', '半段"}\n\nevent: delta\ndata: {"text":"后半段"}\n\n']),
    }) as unknown as typeof fetch

    let text = ''
    await ragApi.askStream(
      { question: 'q', disease: 'breast' },
      { onDelta: (t) => (text += t) },
    )
    expect(text).toBe('前半段后半段')
  })

  it('surfaces the server message when the stream request itself fails', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      body: null,
      json: async () => ({ message: '请求过于频繁' }),
    }) as unknown as typeof fetch

    const onError = vi.fn()
    await ragApi.askStream({ question: 'q', disease: 'breast' }, { onError })
    expect(onError).toHaveBeenCalledWith('请求过于频繁')
  })

  it('sends the bearer token — the reason this uses fetch and not EventSource', async () => {
    tokenStore.set('tok-123')
    const spy = vi.fn().mockResolvedValue({ ok: true, body: stream([]) })
    global.fetch = spy as unknown as typeof fetch

    await ragApi.askStream({ question: 'q', disease: 'breast' }, {})

    const init = spy.mock.calls[0][1] as RequestInit
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer tok-123')
  })
})
