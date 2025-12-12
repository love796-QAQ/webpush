import os
import json
import logging
from typing import List, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pywebpush import webpush, WebPushException
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
import base64

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Constants
DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
SUBSCRIPTIONS_FILE = os.path.join(DATA_DIR, "subscriptions.json")
VAPID_PRIVATE_KEY_FILE = os.path.join(DATA_DIR, "vapid_private_key.pem")
VAPID_PUBLIC_KEY_FILE = os.path.join(DATA_DIR, "vapid_public_key.pem") # Optional, for reference/serving if needed

# --- Key Management ---
def _is_valid_private_key(pem_text: str) -> bool:
    try:
        serialization.load_pem_private_key(pem_text.encode(), password=None)
        return True
    except Exception as exc:
        logger.warning(f"Existing VAPID key invalid, will regenerate. Details: {exc}")
        return False

def generate_vapid_keys():
    """Generates VAPID keys if they don't exist or are empty."""
    if os.path.isfile(VAPID_PRIVATE_KEY_FILE):
        try:
            with open(VAPID_PRIVATE_KEY_FILE, "r") as f:
                existing = f.read().strip()
                if existing and _is_valid_private_key(existing):
                    logger.info(
                        f"Loaded existing VAPID private key from {VAPID_PRIVATE_KEY_FILE} "
                        f"(len={len(existing)})"
                    )
                    return existing
        except IsADirectoryError:
            # If the path was mistakenly mounted as a directory, fall through to regenerate.
            pass
    
    logger.info("Generating new VAPID keys...")
    private_key = ec.generate_private_key(ec.SECP256R1())
    
    # Save Private Key
    pem_private = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode()
    
    with open(VAPID_PRIVATE_KEY_FILE, "w") as f:
        f.write(pem_private)

    # Save Public Key (for reference, though frontend usually has it hardcoded or fetched)
    public_key = private_key.public_key()
    raw_public = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    b64_public = base64.urlsafe_b64encode(raw_public).decode('utf-8').rstrip("=")
    
    with open(VAPID_PUBLIC_KEY_FILE, "w") as f:
        f.write(b64_public)
        
    logger.info(f"New Public Key: {b64_public}")
    logger.info(
        f"Generated new VAPID keys at {VAPID_PRIVATE_KEY_FILE} "
        f"(private len={len(pem_private)}), public len={len(b64_public)}"
    )
    return pem_private

VAPID_PRIVATE_KEY = generate_vapid_keys()  # stored as str
VAPID_CLAIMS = {"sub": "mailto:admin@example.com"}

def ensure_valid_vapid_key():
    """Validate current VAPID key; regenerate if invalid at runtime."""
    global VAPID_PRIVATE_KEY
    try:
        key_str = VAPID_PRIVATE_KEY.decode() if isinstance(VAPID_PRIVATE_KEY, bytes) else VAPID_PRIVATE_KEY
        serialization.load_pem_private_key(key_str.encode(), password=None)
        VAPID_PRIVATE_KEY = key_str  # normalize back to str
        logger.info(
          f"Using VAPID private key (len={len(VAPID_PRIVATE_KEY)}), "
          f"path={VAPID_PRIVATE_KEY_FILE}"
        )
    except Exception as exc:
        logger.warning(f"VAPID key invalid at runtime ({exc}); regenerating.")
        VAPID_PRIVATE_KEY = generate_vapid_keys()

# --- Models ---
class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str

class SubscriptionInfo(BaseModel):
    endpoint: str
    keys: SubscriptionKeys

class BroadcastPayload(BaseModel):
    title: str
    body: str

# --- Storage ---
def load_subscriptions() -> List[dict]:
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return []
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return []

def save_subscription(sub: dict):
    subs = load_subscriptions()
    # Avoid duplicates based on endpoint
    for s in subs:
        if s.get("endpoint") == sub.get("endpoint"):
            return # Already exists
    
    subs.append(sub)
    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(subs, f, indent=2)

def remove_subscription(endpoint: str):
    subs = load_subscriptions()
    new_subs = [s for s in subs if s.get("endpoint") != endpoint]
    if len(new_subs) != len(subs):
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(new_subs, f, indent=2)

# --- Routes ---

@app.post("/api/subscribe")
def subscribe(sub: SubscriptionInfo):
    """Save a new subscription."""
    save_subscription(sub.dict())
    logger.info(f"New subscriber: {sub.endpoint[:20]}...")
    return {"status": "success", "message": "Subscription saved"}

@app.post("/api/broadcast")
def broadcast(payload: BroadcastPayload):
    """Send push notification to all subscribers."""
    ensure_valid_vapid_key()
    subs = load_subscriptions()
    logger.info(
        f"Broadcasting to {len(subs)} subscribers with VAPID key path={VAPID_PRIVATE_KEY_FILE}, "
        f"len={len(VAPID_PRIVATE_KEY)}"
    )
    
    results = {"success": 0, "failed": 0, "removed": 0}
    
    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps(payload.dict()),
                # Pass the path so pywebpush reads the PEM from disk
                vapid_private_key=VAPID_PRIVATE_KEY_FILE,
                vapid_claims=VAPID_CLAIMS
            )
            results["success"] += 1
        except WebPushException as ex:
            logger.error(f"WebPush Error: {ex}")
            if ex.response is not None and ex.response.status_code == 410:
                # 410 Gone: Subscription is no longer valid
                remove_subscription(sub["endpoint"])
                results["removed"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            logger.error(f"General Error: {e}")
            results["failed"] += 1
            
    return {"status": "completed", "results": results}

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    # Return the admin HTML page
    with open("admin.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/vapid-public-key")
def vapid_public_key():
    """Expose the current VAPID public key for frontend to fetch dynamically."""
    ensure_valid_vapid_key()
    if os.path.isfile(VAPID_PUBLIC_KEY_FILE):
        with open(VAPID_PUBLIC_KEY_FILE, "r") as f:
            key = f.read().strip()
            if key:
                logger.info(f"Serving VAPID public key to client: {key[:12]}... (len={len(key)})")
                return {"publicKey": key}
    raise HTTPException(status_code=500, detail="VAPID public key not available")

@app.get("/")
def index_page():
    return FileResponse("index.html")

@app.get("/{path:path}")
def static_files(path: str):
    """Serve static files (sw.js, manifest.json, etc.)"""
    if os.path.exists(path) and os.path.isfile(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="File not found")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
