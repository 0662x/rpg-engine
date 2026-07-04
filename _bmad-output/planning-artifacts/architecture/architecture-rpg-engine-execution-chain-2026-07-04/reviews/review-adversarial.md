# Review - Adversarial

## Verdict

Pass after adversarial read. I did not find a decision that weakens the canonical execution-chain invariant.

## Attack Findings

- No critical or high findings.
- The most likely loophole is treating trusted low-level `commit_turn` as a player UI shortcut. AD-1 and AD-3 close this by separating ordinary player-safe authority from trusted low-level authority.
- The second likely loophole is turning preflight into a cache of permission or proposal state. AD-2 explicitly forbids proposal/permission cache semantics.
- The third likely loophole is treating projection artifacts as facts when SQLite write/projection refresh disagree. AD-4 keeps projection/outbox repairable and non-authoritative.
- The fourth likely loophole is hiding regressions inside "small" adapter changes. AD-5 requires every story to name its category and boundary tests.

## Residual Risk

The spine cannot by itself prevent future code from adding a new mixed-authority surface. That risk is handled by AD-3 plus required story/review gates, not by more spine detail.
