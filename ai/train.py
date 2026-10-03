# -*- coding: utf-8 -*-
"""QLoRA 微调 Qwen2.5-1.5B-Instruct：体检结构化数据 -> 自然语言解读 + 选址建议。

依赖：torch(cu128) transformers peft datasets accelerate bitsandbytes
运行（ai\.venv）:
    python ai/train.py
产物：ai/models/qwen15min-lora/  (adapter + tokenizer，供 ai/server.py 加载)
"""
import json
from pathlib import Path

import datasets
import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    DataCollatorForSeq2Seq,
    Trainer,
    TrainingArguments,
)

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
OUT = ROOT / "models" / "qwen15min-lora"
DATA = ROOT / "data"


def build_messages(example: dict) -> list[dict]:
    content = example["instruction"] + "\n\n体检数据：\n" + (example.get("input") or "")
    return [
        {"role": "user", "content": content},
        {"role": "assistant", "content": example["output"]},
    ]


def tokenize_one(tokenizer, example: dict) -> dict:
    """手动构造 chat 文本并掩码 prompt：Qwen 模板不含 {% generation %}，
    transformers 的 assistant_tokens_mask 不可靠，改为“前缀 -100”方案。"""
    msgs = build_messages(example)
    # 1) prompt = system + user（含 <|im_start|>assistant 提示）
    prompt_text = tokenizer.apply_chat_template(
        msgs[:-1], tokenize=False, add_generation_prompt=True)
    # 2) 完整文本 = prompt + 回答 + eos
    full_text = prompt_text + msgs[-1]["content"] + tokenizer.eos_token
    pre = len(tokenizer(prompt_text, add_special_tokens=False)["input_ids"])
    enc = tokenizer(full_text, add_special_tokens=False)
    ids = enc["input_ids"]
    labels = [-100] * pre + ids[pre:]
    return {"input_ids": ids, "attention_mask": enc["attention_mask"], "labels": labels}


def main() -> None:
    train_raw = json.loads((DATA / "train.json").read_text(encoding="utf-8"))
    dev_raw = json.loads((DATA / "dev.json").read_text(encoding="utf-8"))
    print(f"train={len(train_raw)} dev={len(dev_raw)}")

    tokenizer = AutoTokenizer.from_pretrained(str(BASE), trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "left"

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(BASE),
        quantization_config=bnb,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    train_ds = datasets.Dataset.from_list(train_raw)
    dev_ds = datasets.Dataset.from_list(dev_raw)
    cols = train_ds.column_names
    train_tok = train_ds.map(lambda x: tokenize_one(tokenizer, x), remove_columns=cols)
    dev_tok = dev_ds.map(lambda x: tokenize_one(tokenizer, x), remove_columns=cols)

    args = TrainingArguments(
        output_dir=str(OUT),
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=4,
        num_train_epochs=6,
        learning_rate=2e-4,
        bf16=True,
        logging_steps=5,
        save_strategy="steps",
        save_steps=10,
        eval_strategy="steps",
        eval_steps=10,
        save_total_limit=2,
        warmup_steps=2,
        lr_scheduler_type="cosine",
        max_grad_norm=1.0,
        remove_unused_columns=False,
        report_to=[],
        dataloader_num_workers=0,
    )
    collator = DataCollatorForSeq2Seq(tokenizer=tokenizer, padding=True, label_pad_token_id=-100)
    trainer = Trainer(
        model=model, args=args, train_dataset=train_tok, eval_dataset=dev_tok,
        data_collator=collator, processing_class=tokenizer,
    )
    trainer.train()
    model.save_pretrained(str(OUT))
    tokenizer.save_pretrained(str(OUT))
    print("saved adapter ->", OUT)


if __name__ == "__main__":
    main()
