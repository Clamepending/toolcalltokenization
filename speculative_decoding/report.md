# Speculative Decoding on Amazon Trace Continuations

Date: 2026-03-30

## Setup

- corpus: OttoAuth Amazon canonical traces
- filter: keep episodes with at least `6` canonical actions
- usable episodes: `14`
- split: `11` train, `3` held out
- target model: `mlx-community/Qwen2.5-1.5B-Instruct-4bit`
- draft model: `mlx-community/Qwen2.5-0.5B-Instruct-4bit`
- evaluation prompt: first `50%` of each held-out trace
- continuation length: tokenized length of the remaining held-out suffix

Main artifacts:

- baseline benchmark:
  [amazon_speculative_baseline.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_speculative_baseline.json)
- LoRA benchmark:
  [amazon_speculative_lora.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_speculative_lora.json)
- comparison figure:
  [speculative_decoding_amazon_sweep.svg](/Users/mark/Desktop/projects/toolcalltokenization/docs/figures/speculative_decoding_amazon_sweep.svg)
- proxy baseline:
  [amazon_proxy_baseline.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_proxy_baseline.json)
- proxy LoRA:
  [amazon_proxy_lora.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_proxy_lora.json)
- proxy figure:
  [speculative_proxy_amazon_sweep.svg](/Users/mark/Desktop/projects/toolcalltokenization/docs/figures/speculative_proxy_amazon_sweep.svg)
- draft-only comparison:
  [amazon_draft_only_comparison.json](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_draft_only_comparison.json)

## Smaller-Model-Only Proxy

To match the cheaper measurement setup, I also evaluated the small draft model directly on held-out trace tokens without any larger target model in the loop.

Metric:

- acceptance proxy = held-out next-token agreement under the gold trace prefix
- speedup proxy = analytical upper bound from acceptance probability and draft horizon only

Proxy results:

- base 0.5B draft next-token agreement: `82.17%`
- LoRA 0.5B draft next-token agreement: `85.99%`

Analytical upper-bound speedups from that proxy:

- base draft:
  - `h=1`: `1.822x`
  - `h=2`: `2.497x`
  - `h=4`: `3.507x`
  - `h=6`: `4.189x`
  - `h=8`: `4.650x`
- LoRA draft:
  - `h=1`: `1.860x`
  - `h=2`: `2.599x`
  - `h=4`: `3.782x`
  - `h=6`: `4.656x`
  - `h=8`: `5.302x`

Interpretation:

- under the small-model-only proxy, LoRA helps
- under the exact draft-vs-target benchmark, the same LoRA hurts
- so the adapter improved trace imitation but reduced agreement with the untuned target

## Baseline Result

The untuned 0.5B draft is already fairly well aligned with the 1.5B target on held-out Amazon trace continuations.

- `draft_length=1`: `48.73%` acceptance, `0.991x` speedup
- `draft_length=2`: `65.61%` acceptance, `1.143x` speedup
- `draft_length=4`: `78.98%` acceptance, `1.171x` speedup
- `draft_length=6`: `84.08%` acceptance, `1.055x` speedup
- `draft_length=8`: `87.90%` acceptance, `1.124x` speedup

Best observed point:

- `draft_length=4`
- `78.98%` accepted tokens
- `1.171x` wall-clock speedup versus target-only decoding

Interpretation:

- acceptance rises steadily with draft length
- speed does not rise monotonically
- the sweet spot on this machine is around `4` drafted tokens, not the maximum tested length

## Lightweight LoRA Result

I ran a small MLX LoRA on the 0.5B draft:

- fine-tune type: LoRA
- trainable parameters: `1.466M`
- iters: `60`
- batch size: `1`
- tuned layers: `8`

Result: speculative decoding got worse, not better.

- `draft_length=1`: `46.50%` acceptance, `0.867x` speedup
- `draft_length=2`: `61.46%` acceptance, `0.934x` speedup
- `draft_length=4`: `72.29%` acceptance, `0.843x` speedup
- `draft_length=6`: `77.07%` acceptance, `0.724x` speedup
- `draft_length=8`: `81.53%` acceptance, `0.700x` speedup

So the draft adapter reduced acceptance by about `2-7` points depending on draft length, and all tested settings became slower than or equal to the target-only baseline.

## Why LoRA Hurt Speculative Decoding

The adapter did improve the draft model's fit to the Amazon trace corpus itself.

Draft-only held-out gold prefix match:

- base draft: `1.91%`
- LoRA draft: `12.10%`

That means the adapter learned the trace distribution, but it moved the draft away from the untuned 1.5B target. For speculative decoding, **agreement with the target** matters more than raw domain specialization.

## Current Takeaway

On these Amazon traces:

- speculative decoding is already promising with a small untuned Qwen draft
- the best current point is about `1.17x` speedup at `draft_length=4`
- naive domain LoRA on the draft is not automatically helpful
- if we want to improve speculative performance further, the next better bets are:
  - tune the draft to imitate the target more directly
  - tune both draft and target together
  - use a trace-specialized draft only if the target is also adapted or the objective explicitly preserves agreement
