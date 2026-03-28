# toolcalltokenization

Research notes and experimental planning for learning reusable browser-agent or tool-call action chunks from traces.

## Contents

- [Browser-agent tool tokenization report](./browser-agent-tool-tokenization-report.md)

## Focus

This repo currently contains:

- a literature review of browser-agent trace datasets and tool-use benchmarks
- a proposal for BPE-style or slot-aware action-chunk mining
- a concrete study design for measuring speed, accuracy, and cost

## Next likely steps

- define a canonical trace schema
- build an offline macro miner
- integrate a hybrid primitive+macro agent with BrowserGym / AgentLab
- run controlled evaluations on WorkArena, WebArena, and VisualWebArena
