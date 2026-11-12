"""Demo seeding helpers for the ProofBridge demo video.

Targets the ISOLATED demo database (demo_video.db) served on port 8001 so the
user's real app data (proofbridge.db) is never touched.

Actions:
  users                 create reviewer/buyer/seller demo accounts
  stage --project N     agreement + 3 requirements + in_progress for project N
  full                  users + case + evidence + analysis (validation only)
"""

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./demo_video.db")
os.environ.setdefault("UPLOAD_DIR", "./demo_uploads")

import fitz
import httpx
from PIL import Image, ImageDraw, ImageFont

BASE = "http://127.0.0.1:8001"
PASSWORD = "demo12345"
BUYER_EMAIL = "buyer@demo.com"
SELLER_EMAIL = "seller@demo.com"
AGENT_EMAIL = "agent@demo.com"

ASSETS = Path(__file__).parent / "demo_assets"

REQUIREMENTS = [
    "Order #PB-1042 was placed on March 14, 2026 for a wireless charging pad that never arrived.",
    "I was charged twice for order #PB-9999 on my credit card.",
    "The package that did arrive was shipped to the wrong address and arrived two weeks late.",
]

CASE_TITLE = "Smartphone Charger Order #PB-1042"
CASE_DESCRIPTION = (
    "Customer reports that order #PB-1042 never arrived and that "
    "their credit card was charged twice for the purchase."
)


def make_assets() -> None:
    ASSETS.mkdir(exist_ok=True)

    img = Image.new("RGB", (1200, 900), (17, 24, 39))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=36)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((80, 120), "PROOFBRIDGE MARKETPLACE", fill=(96, 165, 250), font=font)
    draw.text((80, 190), "Service Agreement", fill=(255, 255, 255), font=font)
    draw.text((80, 260), f"Case: {CASE_TITLE}", fill=(203, 213, 225), font=font)
    draw.text((80, 320), "Amount: $29.99 USD", fill=(203, 213, 225), font=font)
    draw.text((80, 380), "This document records the promised scope of the order.", fill=(148, 163, 184), font=font)
    img.save(ASSETS / "service-agreement.png")

    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "PROOFBRIDGE MARKETPLACE",
        "",
        "Order Confirmation",
        "",
        "Order #PB-1042",
        "Date: March 14, 2026",
        "Item: Wireless Charging Pad, Qty 1",
        "Price: $29.99 USD",
        "Payment: Credit Card",
        "Seller: TechGear Store",
        "Shipping Address: 42 Maple Street, Springfield",
    ]
    y = 100
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 24
    doc.save(ASSETS / "order-confirmation-PB-1042.pdf")
    doc.close()

    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "COURIER DELIVERY NOTE",
        "",
        "Shipment for Order #PB-1042",
        "Status: Delivered",
        "",
        "Note: The package was shipped to the wrong address and arrived two weeks late.",
        "Delivered To: 7 Elm Avenue",
        "Carrier: FastShip Express",
    ]
    y = 100
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 24
    doc.save(ASSETS / "shipping-delivery-note.pdf")
    doc.close()
    print("assets ready in", ASSETS)


def ensure_reviewer() -> None:
    from app.database import SessionLocal
    from app.models import User
    from app.security import hash_password

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == AGENT_EMAIL).first()
        if existing:
            print("reviewer exists, id =", existing.id)
            return
        user = User(
            name="Support Agent",
            email=AGENT_EMAIL,
            password_hash=hash_password(PASSWORD),
            role="reviewer",
        )
        db.add(user)
        db.commit()
        print("reviewer created, id =", user.id)
    finally:
        db.close()


def api(method: str, path: str, token: str | None = None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.request(method, BASE + path, headers=headers, timeout=120, trust_env=False, **kwargs)
    if resp.status_code >= 400:
        print(f"  !! {method} {path} -> {resp.status_code}: {resp.text[:300]}")
    return resp


def register_or_login(email: str, name: str, role: str) -> dict:
    resp = api("POST", "/auth/register", json={
        "name": name, "email": email, "password": PASSWORD, "role": role,
    })
    if resp.status_code in (200, 201):
        print(f"registered {email} (id={resp.json()['id']})")
    else:
        print(f"register {email} -> {resp.status_code} (already exists?)")
    resp = api("POST", "/auth/login", data={"username": email, "password": PASSWORD})
    token = resp.json()["access_token"]
    me = api("GET", "/auth/me", token=token).json()
    print(f"logged in {email}: id={me['id']} role={me['role']}")
    return {**me, "token": token}


def cmd_users() -> None:
    make_assets()
    ensure_reviewer()
    register_or_login(BUYER_EMAIL, "Demo Buyer", "client")
    register_or_login(SELLER_EMAIL, "Demo Seller", "freelancer")
    print("users ready")


def cmd_stage(project_id: int) -> None:
    buyer = register_or_login(BUYER_EMAIL, "Demo Buyer", "client")
    bt = buyer["token"]

    state = api("GET", f"/projects/{project_id}", token=bt).json()
    print("project status:", state["status"])

    if not state.get("agreement_name"):
        with open(ASSETS / "service-agreement.png", "rb") as fh:
            resp = api(
                "POST", f"/projects/{project_id}/agreement", token=bt,
                files={"file": ("service-agreement.png", fh, "image/png")},
            )
        print("agreement upload:", resp.status_code)

    reqs = api("GET", f"/projects/{project_id}/requirements", token=bt).json()
    if len(reqs) < len(REQUIREMENTS):
        for text in REQUIREMENTS[len(reqs):]:
            resp = api(
                "POST", f"/projects/{project_id}/requirements", token=bt,
                json={"text": text},
            )
            print("requirement add:", resp.status_code, resp.json().get("id"))

    state = api("GET", f"/projects/{project_id}", token=bt).json()
    if state["status"] == "created":
        resp = api(
            "PATCH", f"/projects/{project_id}/status", token=bt,
            json={"status": "in_progress", "note": "Order marked in progress."},
        )
        print("-> in_progress:", resp.status_code)

    print("staged project", project_id)


def cmd_full() -> None:
    make_assets()
    ensure_reviewer()
    buyer = register_or_login(BUYER_EMAIL, "Demo Buyer", "client")
    seller = register_or_login(SELLER_EMAIL, "Demo Seller", "freelancer")
    bt, st = buyer["token"], seller["token"]

    resp = api("POST", "/projects", token=bt, json={
        "title": CASE_TITLE,
        "description": CASE_DESCRIPTION,
        "freelancer_id": seller["id"],
        "amount": "29.99",
        "currency": "USD",
    })
    if resp.status_code >= 400:
        projects = api("GET", "/projects", token=bt).json()
        project = next((p for p in projects if p["title"] == CASE_TITLE), None)
        if project is None:
            sys.exit("could not create or find demo project")
        print("reusing existing project", project["id"])
    else:
        project = resp.json()
        print("project created, id =", project["id"])

    cmd_stage(project["id"])

    evidence = api("GET", f"/projects/{project['id']}/evidence", token=bt).json()
    existing_names = {e["filename"] for e in evidence}
    for fname in ["order-confirmation-PB-1042.pdf", "shipping-delivery-note.pdf"]:
        if fname in existing_names:
            continue
        with open(ASSETS / fname, "rb") as fh:
            resp = api(
                "POST", f"/projects/{project['id']}/evidence", token=st,
                files={"file": (fname, fh, "application/pdf")},
            )
        print(f"evidence {fname}:", resp.status_code)

    print("running analysis...")
    resp = api("POST", f"/projects/{project['id']}/analysis", token=bt)
    if resp.status_code >= 400:
        sys.exit(f"analysis failed: {resp.text[:500]}")
    content = resp.json()

    print("\n===== REQUIREMENT FINDINGS =====")
    for f in content["requirement_findings"]:
        print(f"- req {f['requirement_id']}: {f['status']} | {f['rationale'][:100]}")

    out = ASSETS / "analysis_result.json"
    out.write_text(json.dumps(content, indent=2, default=str))
    print("\nfull result saved to", out)
    print("PROJECT_ID =", project["id"])


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("users")
    p_stage = sub.add_parser("stage")
    p_stage.add_argument("--project", type=int, required=True)
    sub.add_parser("full")
    args = parser.parse_args()

    if args.action == "users":
        cmd_users()
    elif args.action == "stage":
        cmd_stage(args.project)
    elif args.action == "full":
        cmd_full()


if __name__ == "__main__":
    main()
