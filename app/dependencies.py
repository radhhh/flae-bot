"""FastAPI dependencies for Discord bot."""
import os
from typing import Any, Dict

from fastapi import Header, HTTPException, Request
from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey


DISCORD_PUBLIC_KEY = os.environ.get("DISCORD_PUBLIC_KEY")

if not DISCORD_PUBLIC_KEY:
    raise RuntimeError("Set DISCORD_PUBLIC_KEY env var")


async def verify_discord_request(
    request: Request,
    x_signature_ed25519: str = Header(..., alias="X-Signature-Ed25519"),
    x_signature_timestamp: str = Header(..., alias="X-Signature-Timestamp"),
) -> Dict[str, Any]:
    """
    Verify Discord request signature and return parsed payload.
    
    Discord signs: timestamp + raw_body
    Verify using app public key (Ed25519).
    """
    raw_body = await request.body()
    
    try:
        verify_key = VerifyKey(bytes.fromhex(DISCORD_PUBLIC_KEY))
        message = x_signature_timestamp.encode("utf-8") + raw_body
        verify_key.verify(message, bytes.fromhex(x_signature_ed25519))
    except (BadSignatureError, ValueError) as e:
        raise HTTPException(status_code=401, detail="Invalid request signature") from e
    
    # Parse and return payload
    payload: Dict[str, Any] = await request.json()
    return payload
