r"""15分钟生活圈 · AI 解读推理服务（独立进程，FastAPI :8010）。

加载微调后的 Qwen2.5-1.5B（QLoRA adapter），把体检结构化结果生成自然语言解读。
主后端 /api/ai/interpret 会代理到本服务；本服务未启动时主后端优雅降级。

启动（ai\.venv 内）:
    python ai/server.py
"""
import argparse
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent          # .../ai
BASE_MODEL = ROOT / "models" / "Qwen2.5-1.5B-Instruct"
ADAPTER_DIR = ROOT / "models" / "qwen15min-lora"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-server")

app = FastAPI(title="15min-life AI 解读服务", version="1.0.0")

# 懒加载：进程启动后才挂载（保持 /api/ai/health 可用）
_model = {"pipe": None, "tokenizer": None, "ok": False}


class InterpretRequest(BaseModel):
    instruction: str
    input: str = ""


def _load():
    if _model["ok"]:
        return
    import torch
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer
    logger.info("loading base model: %s", BASE_MODEL)
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(str(BASE_MODEL), trust_remote_code=True)
    # AutoPeftModelForCausalLM 直接加载微调产物目录（含 adapter 与合并后的 config）
    pipe = AutoPeftModelForCausalLM.from_pretrained(
        str(ADAPTER_DIR),
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    pipe.eval()
    _model["pipe"] = pipe
    _model["tokenizer"] = tokenizer
    _model["ok"] = True
    logger.info("model ready in %.1fs", time.time() - t0)


@app.get("/api/ai/health")
async def health():
    return {
        "status": "ok",
        "model_loaded": _model["ok"],
        "model": "Qwen2.5-1.5B-Instruct (QLoRA)",
    }


@app.post("/api/ai/interpret")
async def interpret(req: InterpretRequest):
    try:
        _load()
    except Exception as exc:
        logger.exception("model load failed")
        raise HTTPException(status_code=503, detail=f"AI 模型加载失败：{exc}") from exc

    tokenizer = _model["tokenizer"]
    pipe = _model["pipe"]
    messages = [{"role": "user", "content": req.instruction + "\n\n体检数据：\n" + (req.input or "")}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    import torch
    inputs = tokenizer(text, return_tensors="pt").to(pipe.device)
    with torch.inference_mode():
        gen = pipe.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
            repetition_penalty=1.05,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
        )
    out = tokenizer.decode(gen[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    return {"interpretation": out, "elapsed_ms": round(time.time() * 1000)}


if __name__ == "__main__":
    import uvicorn
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
