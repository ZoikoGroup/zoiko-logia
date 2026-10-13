"""A tiny randomly initialized language model proves both trainers update weights.

No downloaded model, production feedback, or production activation. This test
checks mechanics only; it does not establish improvement on real questions.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.training.data import write_bundle
from app.training.evaluation import evaluate_candidate
from app.training.trainer import run_training


def smoke_training() -> dict:
    import torch
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import WhitespaceSplit
    from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
    torch.set_num_threads(1)
    torch.manual_seed(42)
    with tempfile.TemporaryDirectory(prefix="kriton-training-smoke-") as directory:
        root = Path(directory)
        vocab = {word: i for i, word in enumerate(
            ['[PAD]', '[UNK]', '[BOS]', '[EOS]', 'question', '{"answer":0}', '{"answer":1}'])}
        backend = Tokenizer(WordLevel(vocab, unk_token='[UNK]'))
        backend.pre_tokenizer = WhitespaceSplit()
        tokenizer = PreTrainedTokenizerFast(tokenizer_object=backend, pad_token='[PAD]',
                                            unk_token='[UNK]', bos_token='[BOS]', eos_token='[EOS]')
        tokenizer.chat_template = ("{% for message in messages %}{{ message['content'] + ' ' }}"
                                   "{% endfor %}{% if not add_generation_prompt %}{{ eos_token }}{% endif %}")
        base = root / 'tiny-model'
        model = GPT2LMHeadModel(GPT2Config(vocab_size=len(vocab), n_positions=128,
                                         n_embd=16, n_layer=1, n_head=1,
                                         bos_token_id=2, eos_token_id=3, pad_token_id=0))
        model.save_pretrained(base); tokenizer.save_pretrained(base)
        results = {}
        for mode in ('sft', 'grpo'):
            rows = [{"id": str(i), "group": f"case-{i}",
                     "prompt": [{"role": "user", "content": "question"}],
                     **({"completion": [{"role": "assistant", "content": '{"answer":0}'}]}
                        if mode == 'sft' else {"expected": "0"})} for i in range(6)]
            data = root / f'{mode}-data'
            write_bundle(data, tenant_id='smoke', kind=mode, train=rows[:4], holdout=rows[4:])
            results[mode] = run_training(dataset=data, output=root / mode, base_model=str(base),
                                         mode=mode, steps=12, cpu=True, smoke=True)
        # Exercise the normal LoRA path and continuation from a saved adapter,
        # not just full-weight updates on the diagnostic model.
        lora_rows = [{"id": f"lora-{i}", "group": f"lora-{i}",
                      "prompt": [{"role": "user", "content": f"question {i}"}],
                      "completion": [{"role": "assistant", "content": '{"answer":0}'}]}
                     for i in range(60)]
        lora_data = root / 'lora-data'
        write_bundle(lora_data, tenant_id='smoke', kind='sft', train=lora_rows[:50], holdout=lora_rows[50:])
        lora_output = root / 'lora-candidate'
        lora = run_training(dataset=lora_data, output=lora_output, base_model=str(base),
                            mode='sft', steps=2, cpu=True)
        comparison = evaluate_candidate(dataset=lora_data, candidate=lora_output,
                                        output=root / 'comparison.json')
        continued = run_training(dataset=root / 'grpo-data', output=root / 'continued-rl',
                                 base_model=str(base), adapter=lora_output, mode='grpo',
                                 steps=12, cpu=True, smoke=True)
        return {"sft_weights_changed": results['sft']['weights_changed'],
                "rl_weights_changed": results['grpo']['weights_changed'],
                "evaluation_completed": True, "evaluation_gate_passed": comparison["holdout_gate_passed"],
                "rl_algorithm": "GRPO", "lora_weights_changed": lora["weights_changed"],
                "adapter_continuation_weights_changed": continued["weights_changed"], "sft_steps": results['sft']['steps'],
                "rl_steps": results['grpo']['steps'], "production_eligible": False,
                "scope": "tiny synthetic model; mechanics only"}
