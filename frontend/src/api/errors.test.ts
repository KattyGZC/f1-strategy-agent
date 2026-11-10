import { describe, expect, it } from 'vitest'

import { failureMessage } from './errors.ts'

const BAD_GATEWAY = new Response(null, { status: 502 })

describe('failureMessage', () => {
  it('passes on the detail the API sent', () => {
    expect(failureMessage({ detail: 'too many active replays' }, BAD_GATEWAY)).toBe(
      'too many active replays',
    )
  })

  it.each([
    ['no body', undefined],
    ['a text body', 'Bad Gateway'],
    ['null', null],
    ['no detail', { message: 'x' }],
    ['a validation detail', { detail: [{ msg: 'field required' }] }],
  ])('names the HTTP status for %s', (_, error) => {
    expect(failureMessage(error, BAD_GATEWAY)).toBe('the API answered HTTP 502')
  })
})
