# Speculative Decoding Experiments

This folder contains the lightweight trace-language experiments that compare speculative decoding against the action-macro work.

Current setup:

- corpus: OttoAuth Amazon canonical traces
- filtering: only episodes with at least `6` canonical actions
- split: `ceil(20%)` held out for evaluation
- target model: `mlx-community/Qwen2.5-1.5B-Instruct-4bit`
- draft model: `mlx-community/Qwen2.5-0.5B-Instruct-4bit`

Core scripts:

- [`/Users/mark/Desktop/projects/toolcalltokenization/scripts/run_speculative_trace_benchmark.py`](/Users/mark/Desktop/projects/toolcalltokenization/scripts/run_speculative_trace_benchmark.py)
- [`/Users/mark/Desktop/projects/toolcalltokenization/scripts/generate_speculative_decoding_figures.py`](/Users/mark/Desktop/projects/toolcalltokenization/scripts/generate_speculative_decoding_figures.py)
- [`/Users/mark/Desktop/projects/toolcalltokenization/scripts/prepare_speculative_lora_dataset.py`](/Users/mark/Desktop/projects/toolcalltokenization/scripts/prepare_speculative_lora_dataset.py)

Main outputs:

- baseline benchmark:
  [`/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_speculative_baseline.json`](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_speculative_baseline.json)
- LoRA benchmark:
  [`/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_speculative_lora.json`](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_speculative_lora.json)
- comparison figure:
  [`/Users/mark/Desktop/projects/toolcalltokenization/docs/figures/speculative_decoding_amazon_sweep.svg`](/Users/mark/Desktop/projects/toolcalltokenization/docs/figures/speculative_decoding_amazon_sweep.svg)
- proxy baseline:
  [`/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_proxy_baseline.json`](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_proxy_baseline.json)
- proxy LoRA:
  [`/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_proxy_lora.json`](/Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_proxy_lora.json)
- proxy figure:
  [`/Users/mark/Desktop/projects/toolcalltokenization/docs/figures/speculative_proxy_amazon_sweep.svg`](/Users/mark/Desktop/projects/toolcalltokenization/docs/figures/speculative_proxy_amazon_sweep.svg)

Quick reproduction:

```bash
/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python \
  /Users/mark/Desktop/projects/toolcalltokenization/scripts/run_speculative_trace_benchmark.py

/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python \
  /Users/mark/Desktop/projects/toolcalltokenization/scripts/prepare_speculative_lora_dataset.py

/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python -m mlx_lm lora \
  --train \
  --model mlx-community/Qwen2.5-0.5B-Instruct-4bit \
  --data /Users/mark/Desktop/projects/toolcalltokenization/speculative_decoding/datasets/amazon_trace_lm \
  --adapter-path /Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_qwen05_lora \
  --batch-size 1 \
  --iters 60 \
  --val-batches -1 \
  --learning-rate 1e-4 \
  --steps-per-report 5 \
  --steps-per-eval 10 \
  --save-every 20 \
  --num-layers 8 \
  --max-seq-length 256

/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python \
  /Users/mark/Desktop/projects/toolcalltokenization/scripts/run_speculative_trace_benchmark.py \
  --draft-adapter-path /Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_qwen05_lora \
  --output /Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_speculative_lora.json

/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python \
  /Users/mark/Desktop/projects/toolcalltokenization/scripts/generate_speculative_decoding_figures.py

/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python \
  /Users/mark/Desktop/projects/toolcalltokenization/scripts/run_speculative_proxy_benchmark.py

/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python \
  /Users/mark/Desktop/projects/toolcalltokenization/scripts/run_speculative_proxy_benchmark.py \
  --adapter-path /Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_qwen05_lora \
  --output /Users/mark/Desktop/projects/toolcalltokenization/outputs/speculative_decoding/amazon_proxy_lora.json

/Users/mark/Desktop/projects/toolcalltokenization/.venvbg/bin/python \
  /Users/mark/Desktop/projects/toolcalltokenization/scripts/generate_speculative_proxy_figures.py
```
