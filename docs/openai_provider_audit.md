# OpenAI provider audit

Reviewed on 2026-09-19 by a separate GPT-5.6 Sol agent with high reasoning effort,
with reproductions, fixes, and regression checks in the main task. Scope: the
uncommitted OpenAI API/subscription integration, model selection, desktop settings,
and Codex process lifecycle. The protocol checks used the official Codex CLI
0.155.1 in temporary profiles.

## Confirmed findings and fixes

| Priority | Finding | Resolution |
| --- | --- | --- |
| P1 | The login URL filter rejected the documented `chatgpt.com` origin. | Accept exact HTTPS origins `chatgpt.com` and `auth.openai.com`; reject credentials, unexpected ports, malformed URLs, and lookalike domains. |
| P1 | `thread/start` rejected the `readOnly` sandbox value. | Send `read-only`; confirmed against the actual CLI rather than only the protocol fixture. |
| P2 | Inherited authentication/state variables could bypass the separate PDO profile. | Clear token, API endpoint, workload-identity, and SQLite state overrides from the child environment. |
| P2 | Queued notifications could bypass cancellation and request deadlines. | Check both before consuming queued or buffered messages; add regressions for both paths. |
| P2 | Launcher descendants could retain stdout and block process cleanup. | Stop the owned process tree and avoid closing a stream while its reader holds the lock. Verify with a real POSIX launcher/child pair and mocked Windows cleanup paths. |
| P2 | Model discovery could override a saved selection after settings were cancelled. | Invalidate pending callbacks and restore the saved model even when it is absent from the discovered list. |

The follow-up review found no additional confirmed blocker in these fixes.

## Validation and limits

- Final full suite: **394 passed**, **88% total coverage** (26.73 seconds).
- Ruff lint, formatting, and `git diff --check` pass.
- Regression tests cover login origins, authentication separation, buffered-event
  cancellation/deadlines, process cleanup, and desktop model restoration.
- A repeated suite run exposed an unbounded wait in the existing file-dialog test
  helper. It now waits for filename completion, clicks the actual Open/Save button,
  and uses a watchdog so an unaccepted modal dialog fails instead of hanging.
- An isolated local Responses/SSE server received the actual instructions and
  user text from Codex CLI 0.155.1. The turn completed normally. No real credentials,
  browser login, or external inference requests were used.
- No tools were included in the captured local request. Control runs with tools
  enabled also lacked tools, so this experiment does **not** prove tool suppression
  or filesystem read isolation. Shell, browser, computer, image, plugin, and other
  unneeded feature flags are explicitly disabled; the read-only sandbox is not a
  confidentiality boundary for local files.
- Real ChatGPT login and account-backed generation still need a live end-to-end
  check. Windows process cleanup was mocked, not exercised on Windows.
- A remaining theoretical limitation is that subprocess stdin writes occur before
  the response-wait deadline. A non-reading child with a sufficiently large input
  could block there; this was not reproduced or classified as a confirmed finding.
