"""Thin Bedrock helpers: forced-tool Converse calls (structured output) and Titan embeddings."""

import json
from typing import Any

import boto3

from server.config import AWS_REGION, BEDROCK_EMBED_MODEL_ID

EMBED_DIMS = 1024


def client(service: str) -> Any:
    return boto3.client(service, region_name=AWS_REGION)


def converse_tool(model_id: str, system: str, prompt: str, name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Call Bedrock Converse forcing one tool call; return the tool input."""
    if not model_id:
        raise RuntimeError("Bedrock model ID not set; see .env.example")
    resp = client("bedrock-runtime").converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"temperature": 0, "maxTokens": 4096},
        toolConfig={
            "tools": [{"toolSpec": {"name": name, "inputSchema": {"json": schema}}}],
            "toolChoice": {"tool": {"name": name}},
        },
    )
    return next(c["toolUse"]["input"] for c in resp["output"]["message"]["content"] if "toolUse" in c)


def embed(text: str) -> list[float]:
    """Titan Text Embeddings V2, 1024 dims, normalized (so cosine distance works)."""
    body = json.dumps({"inputText": text[:40000], "dimensions": EMBED_DIMS, "normalize": True})
    resp = client("bedrock-runtime").invoke_model(modelId=BEDROCK_EMBED_MODEL_ID, body=body)
    return json.loads(resp["body"].read())["embedding"]
