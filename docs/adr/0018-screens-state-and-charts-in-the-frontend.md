# 0018. Screens are tabs in the URL, state stays in React, charts are drawn in SVG

- Status: Accepted
- Date: 2026-11-18

## Context

ADR 0005 leaves the routing, state and chart libraries to phase 5, when the simulator screen is built. The frontend has one screen today: `App.tsx` renders the replay screen, with no router. Its data comes from `useEffect` calls through the generated client, each with an `AbortController` and a state that is a discriminated union (`replay/SessionPicker.tsx`), and `useReducer` where the state has transitions (`replay/ReplayView.tsx`). Its dependencies are `react`, `react-dom` and `openapi-fetch`.

The simulator adds a second screen; the assistant (phase 6) will add a third. The simulator shows up to 4 strategies of a race of at most 78 laps (ADR 0017), so a lap-time chart has at most 4 series of 78 points. The frontend renders what the API returns and computes no lap time or strategy outcome (`AGENTS.md`).

## Options

1. **Screens:**
   - **react-router.** Real routes, nested layouts and data loaders. Built for many routes with their own data; here, a dependency and its conventions for two or three screens that share no path parameters.
   - **A tab state in `App`.** No dependency, but a reload or a shared link always opens the replay.
   - **Tabs whose screen lives in `location.hash`.** No dependency; a reload or a link opens the same screen, and the back button moves between screens. The static build needs no server rewrite, since the hash never reaches nginx.
2. **State:** a library (Redux, Zustand, TanStack Query) against the existing pattern. No state is shared between screens, and each call is a single request the screen owns.
3. **Charts:** a library (Recharts, Chart.js) against an SVG component. A library brings tooltips and animation, its weight, and a canvas or measuring code that jsdom does not run; an SVG component of a few lines draws 4 polylines with axes, is queried by role in tests, and takes the CSS tokens of `App.css`.

## Decision

The screens are tabs (the WAI-ARIA Tabs pattern) whose active screen is the hash: `#/replay`, the default, and `#/simulator`; an unknown hash opens the replay. State stays in React, in the existing pattern. Charts are SVG components written here.

## Consequences

- No new dependency. A screen is a member of one closed list, with its hash and its tab.
- Nested routes, route parameters or data loaded by route would need a new ADR.
- A chart's scale (its range and its ticks) is a pure function of the values the API returned, tested on its own; it is presentation, not a strategy computation.
- Every chart has a text equivalent for screen readers: a label that sums it up and a table of its values.
