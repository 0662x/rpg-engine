# Review - Adversarial Divergence

Verdict: PASS

Scope: tried to construct two downstream units that obey the ADs but still build incompatibly.

Findings:

- Critical: none.
- High: none.
- Medium: none after AD-3 was tightened to require a canonical artifact for each contract.
- Low: future stories should choose concrete artifact locations for each contract family, but that is correctly below spine altitude.

Attack cases:

- Unit A implements relationship reads by inspecting `details_json`; Unit B implements relationship reads through a normalized service. AD-4 blocks this: callers must use named relationship/progress access contracts, not storage internals.
- Unit A lets resident AI create and commit missing entities; Unit B routes entity suggestions through validation. AD-2 and AD-6 block this: AI is advisory only and cannot commit or bypass validation.
- Unit A updates Scenario Package relationship YAML during play; Unit B writes runtime relationship changes to Save Package. AD-1 blocks this: normal play cannot write runtime facts back into Scenario Package.
- Unit A treats Context Slice as rendered prompt text; Unit B treats it as structured context. AD-5 blocks this: Context Slice is inspectable structured output before rendering.
- Unit A adds a genre-specific mechanic directly into Kernel; Unit B expresses it through scenario capability and hooks. AD-7 blocks the direct Kernel fork unless promoted through a later architecture/story.
- Unit A treats preflight timeout as permission to commit deterministic fallback; Unit B returns clarification. AD-8 plus inherited execution-chain ADs block unsafe commit.
