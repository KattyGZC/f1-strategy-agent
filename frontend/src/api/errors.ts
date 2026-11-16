/**
 * What to tell the viewer about a failed API call: the API's own detail when it sent one, and
 * the request id it answered under, so the failure can be found in the logs (ADR 0016).
 */
export function failureMessage(error: unknown, response: Response): string {
  const message = detailOf(error) ?? `the API answered HTTP ${response.status}`
  const requestId = response.headers.get('X-Request-ID')
  return requestId === null ? message : `${message} (request ${requestId})`
}

function detailOf(error: unknown): string | null {
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const { detail } = error
    if (typeof detail === 'string') {
      return detail
    }
  }
  return null
}

export const UNREACHABLE = 'the API is unreachable'
