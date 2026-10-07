import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// One clean DOM and one clean token store per test. Without the localStorage
// reset a test that signs in would leak a token into the next one and quietly
// change what it exercises — the request interceptor reads that key.
afterEach(() => {
  cleanup()
  localStorage.clear()
})
