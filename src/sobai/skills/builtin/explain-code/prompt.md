Explain what the supplied code does, written for a {{audience}}.

Work only from the code in front of you. You cannot see the rest of the
repository, its tests, its call sites, or its runtime configuration, so do
not assert how this code is used elsewhere. Where behaviour depends on
something not shown, name the dependency instead of guessing at it.

Cover these, in order, and only where the code gives you something to say:

1. **Purpose** — what problem this code solves, in two or three sentences.
2. **Flow** — the path through the code for the ordinary case, in order.
3. **Key decisions** — the non-obvious choices, and what each one buys.
4. **Edge cases and failure modes** — empty input, errors, concurrency,
   limits, and resource handling, as far as the code shows them.
5. **Risks** — correctness, security, or performance concerns visible in
   this code. Say plainly when you see none.

Audience guide:

- newcomer: assume general programming knowledge but nothing about this
  codebase; expand the idioms.
- maintainer: assume fluency in the language and domain; focus on decisions
  and their consequences.
- reviewer: keep ordinary behaviour brief and concentrate on correctness,
  edge cases, and risks.

Be concrete. Refer to real identifiers and actual line-level behaviour
rather than paraphrasing in the abstract. Never invent a function,
parameter, type, or import that is not in the supplied code. If the material
is not source code, say so and stop.

Output contract:

Markdown under the section headings above, omitting any section the code
gives you nothing to say about. No preamble, and no line-by-line
restatement of the code as prose.
