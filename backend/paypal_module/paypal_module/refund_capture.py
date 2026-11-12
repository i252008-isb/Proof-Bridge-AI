"""
CLI tool for human customer support agents to execute PayPal refunds for ProofBridge AI.

This standalone CLI script is NEVER imported or mounted by the web application.
It requires manual confirmation by typing 'REFUND' before invoking PayPal APIs.

Usage:
    python refund_capture.py <CAPTURE_ID> [--amount 25.00] [--currency USD] [--note "Refund reason"]
"""

import argparse
import json
import sys

try:
    from .payments import refund_capture
except ImportError:
    try:
        from paypal_module.payments import refund_capture
    except ImportError:
        from payments import refund_capture


def main():
    parser = argparse.ArgumentParser(
        description="ProofBridge Support CLI - Execute a human-approved PayPal refund."
    )
    parser.add_argument("capture_id", help="PayPal Capture ID to refund (e.g. 2GG1234567890123A)")
    parser.add_argument("--amount", type=str, default=None, help="Optional amount to refund (e.g. 50.00). Omit for full refund.")
    parser.add_argument("--currency", type=str, default="USD", help="Currency code (default: USD)")
    parser.add_argument("--note", type=str, default=None, help="Optional note to the buyer/payer")

    args = parser.parse_args()

    capture_id = args.capture_id.strip()
    refund_amount_display = f"{args.amount} {args.currency}" if args.amount else "FULL CAPTURE AMOUNT"

    print("=" * 70)
    print("PROOFBRIDGE AI - HUMAN CUSTOMER SUPPORT REFUND TOOL")
    print("=" * 70)
    print(f"Target Capture ID : {capture_id}")
    print(f"Refund Amount     : {refund_amount_display}")
    print(f"Payer Note        : {args.note or 'None'}")
    print("-" * 70)
    print("WARNING: This action issues an actual refund via PayPal REST API.")
    print("It should ONLY be run by a human support agent after reviewing")
    print("the AI Customer Support Advisory Report and evidence.")
    print("-" * 70)

    try:
        confirmation = input("Type REFUND to confirm and execute: ")
    except EOFError:
        print("\n[ABORTED] No confirmation received.")
        sys.exit(1)

    if confirmation.strip() != "REFUND":
        print(f"\n[ABORTED] Entered '{confirmation.strip()}'. Must type exact 'REFUND'. No action taken.")
        sys.exit(1)

    print("\nExecuting refund with PayPal...")
    try:
        result = refund_capture(
            capture_id=capture_id,
            amount=args.amount,
            currency=args.currency,
            note=args.note,
        )
        print("\n" + "=" * 70)
        print("✓ REFUND SUCCESSFUL")
        print("=" * 70)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print("\n" + "!" * 70)
        print(f"[ERROR] Refund failed: {exc}")
        print("!" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
