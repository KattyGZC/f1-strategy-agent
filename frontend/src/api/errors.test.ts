import { describe, expect, it } from 'vitest'

import { failureMessage } from './errors.ts'

const BAD_GATEWAY = new Response(null, { status: 502 })
const REQUEST_ID = '0123456789abcdef0123456789abcdef'
const TRACED = new Response(null, { status: 404, headers: { 'X-Request-ID': REQUEST_ID } })

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

  it('adds the request id the API answered under', () => {
    expect(failureMessage({ detail: 'replay r1 does not exist', code: 'x' }, TRACED)).toBe(
      `replay r1 does not exist (request ${REQUEST_ID})`,
    )
  })

  it('adds the request id to the status when there is no detail', () => {
    expect(failureMessage(undefined, TRACED)).toBe(
      `the API answered HTTP 404 (request ${REQUEST_ID})`,
    )
  })
})
