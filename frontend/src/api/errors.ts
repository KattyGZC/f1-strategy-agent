/** What to tell the viewer about a failed API call: the API's own detail when it sent one. */
export function failureMessage(error: unknown, response: Response): string {
  if (typeof error === 'object' && error !== null && 'detail' in error) {
    const { detail } = error
    if (typeof detail === 'string') {
      return detail
    }
  }
  return `the API answered HTTP ${response.status}`
}

export const UNREACHABLE = 'the API is unreachable'
