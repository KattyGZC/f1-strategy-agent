import createClient from 'openapi-fetch'

import type { paths } from './schema.ts'

export type ApiClient = ReturnType<typeof createClient<paths>>

export function createApiClient(
  baseUrl: string,
  fetchImpl: typeof fetch = globalThis.fetch,
): ApiClient {
  return createClient<paths>({ baseUrl, fetch: fetchImpl })
}
