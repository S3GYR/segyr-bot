from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _get_stripe():
    try:
        import stripe  # type: ignore
    except Exception as exc:  # pragma: no cover - optional dep
        raise RuntimeError("Stripe SDK non installé") from exc
    api_key = os.getenv("STRIPE_API_KEY")
    if not api_key:
        raise RuntimeError("STRIPE_API_KEY manquant")
    stripe.api_key = api_key
    return stripe


def _get_price_id(plan: str) -> str:
    plan = plan.lower()
    mapping = {
        "starter": os.getenv("STRIPE_PRICE_STARTER"),
        "pro": os.getenv("STRIPE_PRICE_PRO"),
        "enterprise": os.getenv("STRIPE_PRICE_ENTERPRISE"),
    }
    price_id = mapping.get(plan)
    if not price_id:
        raise RuntimeError(f"Price ID non configuré pour le plan {plan}")
    return price_id


def create_customer(email: str, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    stripe = _get_stripe()
    customer = stripe.Customer.create(email=email, name=name, metadata=metadata or {})
    return customer


def create_subscription(customer_id: str, plan: str) -> Dict[str, Any]:
    stripe = _get_stripe()
    price_id = _get_price_id(plan)
    sub = stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}],
        expand=["latest_invoice.payment_intent"],
    )
    return sub


def handle_webhook(payload: bytes, sig_header: str, endpoint_secret: Optional[str] = None) -> Dict[str, Any]:
    stripe = _get_stripe()
    secret = endpoint_secret or os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET manquant")
    event = stripe.Webhook.construct_event(payload=payload, sig_header=sig_header, secret=secret)
    # Retour brut, à router côté API selon type
    return {
        "type": event["type"],
        "data": event["data"],
    }
