"""QLoRA fine-tune of Qwen on validated input -> output pairs, then merge adapters.

Runs inside the SageMaker training container:
  training data   : /opt/ml/input/data/training/train.jsonl
  hyperparameters : /opt/ml/input/config/hyperparameters.json
  model output    : /opt/ml/model  (SageMaker uploads it to the job's output S3 path)
"""
import json
import os

import torch
from datasets import load_dataset
from peft import LoraConfig, PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

TRAIN_FILE = "/opt/ml/input/data/training/train.jsonl"
HP_PATH = "/opt/ml/input/config/hyperparameters.json"
MODEL_DIR = "/opt/ml/model"
MERGED_DIR = "/opt/ml/merged"
ADAPTER_DIR = "/opt/ml/checkpoints/adapter"


def load_hyperparameters() -> dict:
    hp = {}
    if os.path.exists(HP_PATH):
        with open(HP_PATH) as f:
            hp = json.load(f)
    # The SDK/toolkit may JSON-encode values ('"Qwen/..."'); strip surrounding quotes.
    hp = {k: v.strip('"') if isinstance(v, str) else v for k, v in hp.items()}
    return {
        "base_model": hp.get("base_model", "Qwen/Qwen2.5-7B-Instruct"),
        "epochs": float(hp.get("epochs", 3)),
        "learning_rate": float(hp.get("learning_rate", 2e-4)),
        "lora_r": int(hp.get("lora_r", 16)),
        "lora_alpha": int(hp.get("lora_alpha", 32)),
        "max_seq_len": int(hp.get("max_seq_len", 4096)),
        # Where the merged HF model files are uploaded for Bedrock import (set by the pipeline).
        "export_s3_uri": hp["export_s3_uri"],
    }


def main() -> None:
    hp = load_hyperparameters()
    print(f"Hyperparameters: {hp}")

    tokenizer = AutoTokenizer.from_pretrained(hp["base_model"])
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 4-bit quantized frozen base model - the "Q" in QLoRA.
    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        hp["base_model"],
        quantization_config=bnb,
        device_map="auto",
        torch_dtype=torch.bfloat16,
    )

    lora = LoraConfig(
        r=hp["lora_r"],
        lora_alpha=hp["lora_alpha"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    # Each row: {"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}
    # SFTTrainer applies the Qwen chat template to "messages" automatically.
    dataset = load_dataset("json", data_files=TRAIN_FILE, split="train")
    print(f"Training on {len(dataset)} examples")

    cfg = SFTConfig(
        output_dir="/opt/ml/checkpoints",
        num_train_epochs=hp["epochs"],
        learning_rate=hp["learning_rate"],
        max_seq_length=hp["max_seq_len"],
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        gradient_checkpointing=True,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        bf16=True,
        logging_steps=10,
        save_strategy="no",
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        args=cfg,
        train_dataset=dataset,
        peft_config=lora,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.model.save_pretrained(ADAPTER_DIR)

    # Merge: reload the base in bf16 (merging into 4-bit weights is lossy),
    # apply the trained adapter, and bake it into full weights.
    del model, trainer
    torch.cuda.empty_cache()
    base = AutoModelForCausalLM.from_pretrained(
        hp["base_model"], torch_dtype=torch.bfloat16, device_map="auto"
    )
    merged = PeftModel.from_pretrained(base, ADAPTER_DIR).merge_and_unload()
    merged.save_pretrained(MERGED_DIR, safe_serialization=True)
    tokenizer.save_pretrained(MERGED_DIR)
    print(f"Saved merged model to {MERGED_DIR}")

    # Bedrock Custom Model Import needs the raw Hugging Face files (config.json,
    # tokenizer, *.safetensors) under an S3 prefix - not SageMaker's model.tar.gz.
    # Upload them directly and leave only a small manifest in /opt/ml/model so
    # SageMaker doesn't tar and re-upload ~15 GB.
    uploaded = upload_dir(MERGED_DIR, hp["export_s3_uri"])
    os.makedirs(MODEL_DIR, exist_ok=True)
    with open(os.path.join(MODEL_DIR, "manifest.json"), "w") as f:
        json.dump({"export_s3_uri": hp["export_s3_uri"], "files": uploaded, "hyperparameters": hp}, f, indent=1)
    print(f"Uploaded {len(uploaded)} files to {hp['export_s3_uri']}")


def upload_dir(local_dir: str, s3_uri: str) -> list[str]:
    import boto3
    from boto3.s3.transfer import TransferConfig

    assert s3_uri.startswith("s3://"), s3_uri
    bucket, _, prefix = s3_uri[len("s3://"):].partition("/")
    prefix = prefix.rstrip("/") + "/"
    s3 = boto3.client("s3")
    cfg = TransferConfig(multipart_chunksize=256 * 1024 * 1024, max_concurrency=16)
    names = []
    for name in sorted(os.listdir(local_dir)):
        path = os.path.join(local_dir, name)
        if os.path.isfile(path):
            s3.upload_file(path, bucket, prefix + name, Config=cfg)
            names.append(name)
    return names


if __name__ == "__main__":
    main()
