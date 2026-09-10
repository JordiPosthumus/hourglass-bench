# Method: waves of questions

Hourglass Bench measures how much correct work an agent completes within one hour of active wall time. Questions arrive in a fixed sequence of difficulty waves, with subjects mixed throughout. The aim is to expose even an early portion of a run to different kinds of work and different difficulty levels.

Difficulty labels describe the authored bank. They are provisional, not measured probabilities of success. A question that takes a long time may reveal hard reasoning, inefficient verification, slow inference, or a tool problem; duration alone cannot distinguish them.

## The regular wave

When all three difficulty bands contain questions, the underlying sequence repeats:

```text
Easy → Medium → Hard → Easy → Medium → Hard → …
```

Within each band, the scheduler rotates among available subjects, such as charts, games and mathematics. It avoids repeating the preceding subject when an alternative is available. Within a subject and band, questions are ordered by their authored tier and then their stable identifier.

| Question scale | Easy | Medium | Hard |
|---|---|---|---|
| Charts, tiers 1–10 | 1–3 | 4–7 | 8–10 |
| Games, tiers 1–5 | 1–2 | 3 | 4–5 |
| Mathematics without an explicit tier | Advanced high school | Advanced undergraduate | Graduate |

Mathematics education labels map to estimated scheduling tiers 1, 5 and 9 when no numeric tier is supplied. The bands used for scheduling are separate from the fixed scoring weights.

An exhausted band is skipped. Questions with unknown difficulty follow the classified questions. Each selected question appears once in the ordered list; the standard evaluation uses one attempt per question. The sequence is deterministic and does not adapt to a model's answers.

## Challenge questions in the private reference bank

The private version 2.2 evaluation adds a second rhythm: one original rule-system challenge after every four regular questions. In the full reference bank, 100 regular questions and 20 challenges make 120 questions. Challenges occupy positions 5, 10, …, 100; the final 20 positions contain the remaining regular questions.

The regular difficulty cycle continues across each insertion. It does not restart at the beginning of every five-question block. While all three bands remain available, an illustrative sequence is:

| Positions | Four regular questions | Inserted challenge |
|---|---|---|
| 1–5 | Easy → Medium → Hard → Easy | Challenge |
| 6–10 | Medium → Hard → Easy → Medium | Challenge |
| 11–15 | Hard → Easy → Medium → Hard | Challenge |

These blocks are a way to describe the cadence, not separate timed rounds. Challenges follow their fixed authored rank; that rank is not a claim of empirically increasing difficulty. In a selected subset, insertion still follows each four regular questions, and any challenges left when regular questions run out are appended.

Each reference challenge has distinct pilot and held-out input variants, twelve answer choices, and two reference solving methods. Pilot model work is inspected for ambiguity, shortcuts and mistakes in the question. The scored input is held out from those pilots. This provides evidence of solvability; it does not establish uniform difficulty or freedom from every possible shortcut.

**Implementation scope:** the public harness supports regular difficulty waves, challenge insertion after every four regular questions, and two-point challenge weights for user-authored challenge tasks. The public repository ships only the optional hello-world setup demonstration. The reference questions, inputs, answers and pilot traces remain private.

## One clock across all waves

The full ordered run shares 3,600 active seconds. Starting a question or reaching a challenge does not reset the clock. Thinking, tool calls, initialization, grading, errors and retries consume the budget; recorded pauses between resumes do not.

Each question has 900 active seconds total, including tools, retries and repeats; expiry advances to the next question. There is no agent-turn cap. A model may spend substantial time solving or checking a difficult question, leaving less time for later questions. That cost is part of the measurement. Configured model context and output limits still apply.

Each distinct correct answer completed by the inclusive deadline earns its fixed authored weight, normally between one and two points; reference challenges earn two. Raw correct counts remain visible. Under net-hour-v2, an incorrect final answer costs one point; unfinished and unreached questions earn zero. Explicit abstention is not offered. Execution errors are recorded separately from incorrect answers. An early interrupted run is partial and is not extrapolated to a full hour. The existing stop after 20 consecutive incorrect answers can also end a run early.

## Reading and comparing results

The method measures useful work under a shared time budget, including the cost of reasoning and tools. Faster models can reach more questions, while difficult questions offer higher authored weights. The weights are a declared scoring choice, not a calibrated estimate of how much harder each question is.

Mixing difficulty and subjects improves the variety of the early sequence, but it does not give every model the same completed sample. Models that progress at different speeds reach different prefixes of the fixed order. Interpret scores together with elapsed time, completion counts, errors, token usage and the text/vision breakdown.

For a comparison, hold bank content, exact order, repeat policy and scoring rules constant, and keep relevant harness, model and hardware settings equivalent or disclose their differences. New evaluations freeze their order and weights; resumed evaluations retain the saved sequence. Adding challenges creates a different bank and order fingerprint, so an older 100-question run should not be presented as directly equivalent to a new 120-question run.
