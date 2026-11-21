"""Every call to Razorpay lives here.

The SDK is thin, but keeping it behind one module means the views read as HTTP
and the tests patch a single seam rather than a third-party object graph. It also
gives the missing-credential case one shape: absent keys are not an import-time
error, because the site has to boot without a payment account (every free
article keeps working); `is_configured()` is asked per request and checkout
answers 503.

The amount is never taken from the client. `create_order` is handed a value the
caller computed from `Article.price`, which is what stops a browser from naming
its own price.
"""

import razorpay
from django.conf import settings
from razorpay.errors import (
    BadRequestError,
    GatewayError,
    ServerError,
    SignatureVerificationError,
)

# One sentence for every provider failure, so a view cannot accidentally forward
# Razorpay's internal wording (which sometimes names the account or the key).
PROVIDER_UNAVAILABLE = (
    'The payment provider is temporarily unavailable. You have not been charged.'
)


class PaymentGatewayError(Exception):
    """The provider is unconfigured, unreachable, or refused the request."""


def is_configured():
    """Whether checkout can be attempted at all.

    The webhook needs its own secret as well, but it is checked separately:
    payments can be collected before the endpoint is registered in the
    dashboard, and a delivery arriving without a secret is rejected rather than
    silently accepted.
    """
    return bool(settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET)


def _client():
    if not is_configured():
        raise PaymentGatewayError('Payments are not configured.')
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_order(amount_paise, receipt, notes=None):
    """Create a provider order for exactly `amount_paise` rupees-paise (INR).

    `payment_capture=1` asks for automatic capture: the verify endpoint grants
    access the moment Razorpay reports the payment, so there must be no manual
    capture step for somebody to forget.
    """
    payload = {
        'amount': int(amount_paise),
        'currency': 'INR',
        # Razorpay caps the receipt at 40 characters.
        'receipt': receipt[:40],
        'notes': {key: str(value) for key, value in (notes or {}).items()},
        'payment_capture': 1,
    }
    try:
        order = _client().order.create(payload)
    except (BadRequestError, ServerError, GatewayError) as exc:
        raise PaymentGatewayError(PROVIDER_UNAVAILABLE) from exc
    except Exception as exc:  # network failure, malformed response, SDK internals
        raise PaymentGatewayError(PROVIDER_UNAVAILABLE) from exc

    if not order or not order.get('id'):
        raise PaymentGatewayError(PROVIDER_UNAVAILABLE)
    return order


def fetch_payment(payment_id):
    """The provider's own record of one payment.

    Used as a second opinion after signature verification: the signature proves
    the payment is real and bound to our order, and this confirms the amount and
    that it actually captured. A caller that cannot reach the provider should
    treat that as "no second opinion", not as a failed payment.
    """
    try:
        return _client().payment.fetch(payment_id)
    except Exception as exc:
        raise PaymentGatewayError(PROVIDER_UNAVAILABLE) from exc


def verify_payment(params):
    """True when `order_id|payment_id` was signed with our API secret.

    This is the whole security of the checkout: everything the browser sends
    back is a claim until this returns True. A mismatched signature is an
    ordinary `False`, not an exception, because a forged or stale response is a
    refusal rather than an outage.
    """
    try:
        return bool(_client().utility.verify_payment_signature(params))
    except SignatureVerificationError:
        return False


def verify_webhook(body, signature):
    """True when the delivery was signed with the endpoint's webhook secret.

    `body` must be the *raw* request body: the signature covers the bytes as
    sent, so re-serialising the parsed JSON would change the digest.
    """
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        raise PaymentGatewayError('The payment webhook is not configured.')
    try:
        # No client: the webhook secret is independent of the API key pair, and
        # signing is pure HMAC. Requiring the keys here would make a delivery
        # fail for a reason that has nothing to do with the delivery.
        return bool(razorpay.Utility().verify_webhook_signature(body, signature, secret))
    except SignatureVerificationError:
        return False
