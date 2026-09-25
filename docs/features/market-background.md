# Market-themed interactive background

Status: complete
Updated: 2026-09-25

## Goal and scope

Add a subtle profitable-chart and large bullseye background to the redesigned
dashboard. Motion should feel alive without competing with financial data.

## Acceptance criteria

- [x] Background includes an upward chart, quiet candlesticks, and bullseye motif.
- [x] Pointer movement produces slow, low-distance parallax with no interaction blocking.
- [x] Motion respects `prefers-reduced-motion`.
- [x] Dark and light themes use the existing gold design tokens.
- [x] Calendar and Trades pass visual review and retain existing behavior.

## Relevant context

- Presentation only: `base.html` and `portal.css`.
- The decoration is `aria-hidden` and has `pointer-events: none`.
- No external image asset or additional JavaScript dependency is used.

## Verification evidence

Verified on 2026-09-25:

- Flask test client rendered Calendar and Trades with the market backdrop present.
- Browser review confirmed the chart, candles, and bullseye remain subtle behind
  both pages and do not reduce content contrast.
- Existing navigation and Trades controls remained available to accessibility APIs.
- Ran the affected project test suite: 61 passed.
- `git diff --check` reported no whitespace errors (existing CRLF notices only).
- Restarted only the dashboard; the bot process remained running.

## Operational impact

Dashboard restart required. Bot restart is not required.

## Handoff

Complete. The chart traces slowly, target rings breathe gently, and pointer
movement adds a maximum seven-pixel drift. Reduced-motion mode freezes the effect.

Follow-up adjustment: increased the backdrop visibility, changed the profit line
and candlesticks to green, and changed the bullseye to red for clearer market
meaning while retaining the same restrained motion.

Position follow-up: raised the right-side bullseye so its center aligns with the
main page heading rather than the chart panel.

Target-detail follow-up: removed the decorative horn curves from the center and
increased the crosshair opacity and thickness for a cleaner target shape.
