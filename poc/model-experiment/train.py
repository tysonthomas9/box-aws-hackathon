"""SageMaker-only tiny LoRA + full-weight merge, with timing/hash evidence."""

import hashlib
import json
import os
from pathlib import Path
import time
from urllib.parse import urlencode

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
import torch
from peft import LoraConfig, get_peft_model
from torch.utils.data import Dataset
from transformers import (AutoModelForCausalLM, AutoTokenizer, DataCollatorForSeq2Seq,
                          Trainer, TrainingArguments, set_seed)


def main():
    seed = int(os.environ.get("POC_SEED", "42"))
    epochs = float(os.environ.get("POC_EPOCHS", "1"))
    learning_rate = float(os.environ.get("POC_LEARNING_RATE", "0.001"))
    max_length = int(os.environ.get("POC_MAX_LENGTH", "256"))
    accumulation = int(os.environ.get("POC_GRAD_ACCUMULATION", "1"))
    poc_name = os.environ.get("POC_NAME", "sagemaker-bedrock")
    tagging = urlencode({"project": "box-hackathon", "poc": poc_name})
    set_seed(seed)
    started = time.monotonic()
    base = "/opt/ml/input/data/base"
    rows = [json.loads(line) for line in Path("/opt/ml/input/data/data/train.jsonl").read_text().splitlines()]
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    tokenizer.pad_token = tokenizer.eos_token
    lengths = [len(tokenizer.apply_chat_template(row["messages"], tokenize=True,
               add_generation_prompt=False, enable_thinking=False)) for row in rows]
    over512 = sum(length > 512 for length in lengths)
    if over512:
        max_length = 1024
    if any(length > max_length for length in lengths):
        raise ValueError("Training row exceeds approved length1024; stop without dropping rows")
    truncation = {"rows": len(rows), "maximum_tokens": max(lengths),
                  "rows_over_512": over512, "selected_max_length": max_length,
                  "rows_truncated": sum(length > max_length for length in lengths)}
    print("TRUNCATION_GUARD " + json.dumps(truncation), flush=True)
    if json.loads(Path(base, "config.json").read_text())["max_position_embeddings"] != 32768:
        raise ValueError("Expected approved32K base config")
    model = AutoModelForCausalLM.from_pretrained(
        base, torch_dtype=torch.bfloat16, device_map={"": 0}, local_files_only=True,
        attn_implementation="sdpa")
    loaded = time.monotonic()
    model = get_peft_model(model, LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.0, target_modules=["q_proj", "v_proj"],
        task_type="CAUSAL_LM", bias="none"))
    model.config.use_cache = False
    model.enable_input_require_grads()
    model.print_trainable_parameters()

    class ChatRows(Dataset):
        def __len__(self):
            return len(rows)

        def __getitem__(self, index):
            messages = rows[index]["messages"]
            prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
            full = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False, enable_thinking=False)
            tokens = tokenizer(full, add_special_tokens=False, truncation=True, max_length=max_length)
            prefix_length = len(tokenizer(prompt, add_special_tokens=False)["input_ids"])
            if prefix_length >= len(tokens["input_ids"]):
                raise ValueError(f"Row {index} has no assistant tokens at max_length={max_length}")
            tokens["labels"] = [-100] * min(prefix_length, len(tokens["input_ids"])) + tokens["input_ids"][prefix_length:]
            return tokens

    trainer = Trainer(model=model, train_dataset=ChatRows(),
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
        args=TrainingArguments(output_dir="/tmp/trainer", num_train_epochs=epochs,
            per_device_train_batch_size=1, gradient_accumulation_steps=accumulation,
            learning_rate=learning_rate, warmup_ratio=0.0, lr_scheduler_type="constant",
            bf16=True, gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
            logging_steps=1, save_strategy="no", report_to=[], seed=seed,
            dataloader_num_workers=0, optim="adamw_torch"))
    training_started = time.monotonic()
    training = trainer.train()
    training_done = time.monotonic()
    model.save_pretrained("/tmp/adapter")
    merged = model.merge_and_unload()
    merged.config.use_cache = True
    merged.config.max_position_embeddings = 32768
    merged.save_pretrained("/tmp/merged", safe_serialization=True, max_shard_size="4GB")
    tokenizer.save_pretrained("/tmp/merged")
    for name in ["LICENSE", "README.md"]:
        Path("/tmp/merged", name).write_bytes(Path(base, name).read_bytes())
    Path("/tmp/merged/NOTICE").write_text(
        "Qwen3 experiment model, Apache-2.0. Modified for this research POC:\n"
        f"max_position_embeddings capped at32768;{len(rows)}-example {epochs:g}-epoch LoRA merged into full weights.\n")
    merge_done = time.monotonic()
    s3 = boto3.client("s3", region_name="us-east-2", config=Config(
        retries={"mode": "adaptive", "total_max_attempts": 4}))
    bucket = os.environ["POC_BUCKET"]
    prefix = os.environ["POC_OUTPUT_PREFIX"]
    files = {}
    for directory, subprefix in [(Path("/tmp/merged"), "merged"), (Path("/tmp/adapter"), "adapter")]:
        for path in sorted(directory.iterdir()):
            digest = hashlib.sha256()
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                    digest.update(chunk)
            key = f"{prefix}/{subprefix}/{path.name}"
            s3.upload_file(str(path), bucket, key,
                ExtraArgs={"Tagging": tagging},
                Config=TransferConfig(multipart_threshold=16*1024*1024, max_concurrency=4))
            files[key] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    report = {"examples": len(rows), "epochs": epochs, "steps": trainer.state.global_step,
        "seed": seed, "learning_rate": learning_rate, "max_length": max_length,
        "truncation_guard": truncation,
        "gradient_accumulation_steps": accumulation, "poc": poc_name,
        "load_seconds": loaded-started, "training_seconds": training_done-training_started,
        "merge_seconds": merge_done-training_done, "upload_and_hash_seconds": time.monotonic()-merge_done,
        "metrics": training.metrics, "files": files, "cuda_max_memory_bytes": torch.cuda.max_memory_allocated(),
        "merged_s3_uri": f"s3://{bucket}/{prefix}/merged/"}
    s3.put_object(Bucket=bucket, Key=f"{prefix}/report.json", Body=json.dumps(report, indent=2).encode(),
                  Tagging=tagging, ContentType="application/json")
    Path("/opt/ml/model/report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
