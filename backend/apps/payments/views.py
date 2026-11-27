"""Checkout, verification and the webhook.

Three routes, three different kinds of trust:

* `CheckoutView` is the only place an order is created, and it derives the
  amount from `Article.price` — the request names the article, never the money.
* `VerifyPaymentView` is what the browser calls after Razorpay's sheet closes.
  It is an optimisation and a UX path, not the source of truth: the signature is
  checked, but the same grant can also arrive by webhook.
* `RazorpayWebhookView` is the authoritative one. It is unauthenticated by
  necessity — Razorpay has no account here — so the signature over the raw body
  is the entire authentication, and a delivery is recorded before it is acted on
  so a retry cannot grant twice.
"""

import json
import logging
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.articles.models import Article

from . import gateway
from .access import can_read_article
from .models import PaymentEvent, Purchase
from .serializers import (
    CheckoutResponseSerializer,
    CheckoutSerializer,
    MyPurchasesSerializer,
    PaymentStatusSerializer,
    PurchaseLogSerializer,
    PurchaseSummarySerializer,
    VerifyPaymentSerializer,
)

logger = logging.getLogger(__name__)

PAYMENTS_UNAVAILABLE = 'Payments are not configured yet. Nothing has been charged.'


def _find_article(key):
    """Resolve the article the way the rest of the API does: slug first.

    Only published articles are reachable, so a draft cannot be bought (and
    therefore cannot be unlocked) through a stale link.
    """
    article = Article.objects.filter(slug=key, is_published=True).first()
    if not article and str(key).isdigit():
        article = Article.objects.filter(pk=int(key), is_published=True).first()
    return article


def _paid_payload(purchase):
    return {
        'status': 'paid',
        'slug': purchase.article.slug,
        'purchase_id': purchase.pk,
        'has_access': True,
    }


def _remember_contact(purchase, contact):
    """Keep the number the buyer used, so the next sheet starts prefilled.

    Razorpay's payment entity carries the contact the sheet collected; copying
    it onto the attempt is what lets `CheckoutView` stop asking for it on the
    next purchase. Only a non-empty, changed value is written, and never as a
    side effect of the settlement itself: losing this number must not fail a
    payment that already went through.
    """
    if contact and purchase.contact != contact:
        purchase.contact = contact
        purchase.save(update_fields=['contact'])


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CheckoutSerializer,
        responses={200: CheckoutResponseSerializer, 201: CheckoutResponseSerializer},
        summary='Create a Razorpay order for one paid article',
    )
    def post(self, request):
        serializer = CheckoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        article = _find_article(serializer.validated_data['slug'])
        if not article:
            return Response(
                {'detail': 'No published article found matching that slug.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not article.is_paid or article.price < Decimal('1'):
            return Response(
                {'detail': 'This article is free — there is nothing to buy.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # A reader who already owns it (or staff, who can always read it) is
        # answered without an order. Charging twice is the one failure here that
        # costs somebody money.
        if can_read_article(request.user, article):
            return Response({'already_owned': True, 'slug': article.slug})

        if not gateway.is_configured():
            return Response(
                {'detail': PAYMENTS_UNAVAILABLE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # `price` is stored in rupees with two decimals, so this is exact.
        amount_paise = int(article.price * 100)
        purchase = Purchase.objects.create(
            user=request.user,
            article=article,
            amount_paise=amount_paise,
        )

        try:
            order = gateway.create_order(
                amount_paise=amount_paise,
                receipt=purchase.receipt,
                notes={
                    'purchase_id': purchase.pk,
                    'article_slug': article.slug,
                    'user_id': request.user.pk,
                },
            )
        except gateway.PaymentGatewayError as exc:
            # The attempt is closed rather than left open: it has no order id,
            # so nothing can ever settle it.
            logger.warning('Razorpay order creation failed: %s', exc)
            purchase.mark_failed()
            return Response(
                {'detail': str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        purchase.provider_order_id = order['id']
        purchase.save(update_fields=['provider_order_id'])

        # Prefill everything the sheet would otherwise ask for. `contact` comes
        # from the buyer's last settled payment, not from a profile field, so a
        # first purchase pays the cost once and every later one does not.
        last_contact = (
            Purchase.objects.filter(user=request.user)
            .exclude(contact='')
            .order_by('-created_at')
            .values_list('contact', flat=True)
            .first()
        )
        prefill = {'email': request.user.email}
        if request.user.display_name:
            prefill['name'] = request.user.display_name
        if last_contact:
            prefill['contact'] = last_contact

        return Response(
            {
                'purchase_id': purchase.pk,
                'slug': article.slug,
                'key_id': settings.RAZORPAY_KEY_ID,
                'order_id': purchase.provider_order_id,
                'amount': amount_paise,
                'currency': purchase.currency,
                'name': 'CSEHub',
                'description': article.title[:200],
                'prefill': prefill,
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=VerifyPaymentSerializer,
        responses={200: PaymentStatusSerializer, 202: PaymentStatusSerializer},
        summary='Verify a Razorpay payment and unlock the article',
    )
    def post(self, request):
        serializer = VerifyPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Scoped to the caller's own orders: an order id from somebody else's
        # checkout is a 404, not a way to unlock a stranger's purchase.
        purchase = (
            Purchase.objects.select_related('article')
            .filter(user=request.user, provider_order_id=data['razorpay_order_id'])
            .first()
        )
        if not purchase:
            return Response(
                {'detail': 'That payment does not belong to an order of yours.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if purchase.status == Purchase.STATUS_REFUNDED:
            return Response(
                {'detail': 'That purchase was refunded, so access stays closed.'},
                status=status.HTTP_409_CONFLICT,
            )

        # A retried verification (a lost response, a reloaded tab) must be a
        # no-op, not a second grant or an error.
        if purchase.status == Purchase.STATUS_PAID:
            return Response(_paid_payload(purchase))

        if not gateway.is_configured():
            return Response(
                {'detail': PAYMENTS_UNAVAILABLE},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        try:
            verified = gateway.verify_payment(
                {
                    'razorpay_order_id': data['razorpay_order_id'],
                    'razorpay_payment_id': data['razorpay_payment_id'],
                    'razorpay_signature': data['razorpay_signature'],
                }
            )
        except gateway.PaymentGatewayError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if not verified:
            logger.warning('Rejected payment signature for purchase %s', purchase.pk)
            return Response(
                {'detail': 'That payment could not be verified, so nothing was unlocked.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Second opinion, when the provider answers: the signature proves the
        # payment is ours, this proves it is the *right size* and actually
        # captured. A provider that cannot be reached leaves the signature as
        # the decision, which is Razorpay's documented verification flow.
        try:
            payment = gateway.fetch_payment(data['razorpay_payment_id'])
        except gateway.PaymentGatewayError:
            payment = None

        if payment:
            if payment.get('order_id') != purchase.provider_order_id:
                logger.error(
                    'Payment %s belongs to order %s, not purchase %s',
                    data['razorpay_payment_id'], payment.get('order_id'), purchase.pk,
                )
                return Response(
                    {'detail': 'That payment does not match this order.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if int(payment.get('amount') or 0) != purchase.amount_paise:
                logger.error(
                    'Payment %s was for %s paise, purchase %s expects %s',
                    data['razorpay_payment_id'], payment.get('amount'),
                    purchase.pk, purchase.amount_paise,
                )
                return Response(
                    {'detail': 'That payment does not match the price of this article.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if payment.get('status') != 'captured':
                # Authorised but not settled. The webhook will finish the job.
                return Response(
                    {
                        'status': 'pending',
                        'detail': 'The payment is still being confirmed. Refresh in a moment.',
                    },
                    status=status.HTTP_202_ACCEPTED,
                )
            # Remembered before the grant so a retried verification, which
            # returns early while already paid, does not need to do it again.
            _remember_contact(purchase, payment.get('contact', ''))

        purchase.record_payment(data['razorpay_payment_id'])
        return Response(_paid_payload(purchase))


class MyPurchasesView(APIView):
    """List paid articles owned by the currently authenticated reader."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List the authenticated user's purchased articles",
        responses={200: MyPurchasesSerializer(many=True)},
    )
    def get(self, request):
        # A purchase of an article that has since been unpublished is left out:
        # the detail route only serves published articles, so listing it would
        # be a link that 404s for the reader who paid for it.
        purchases = (
            Purchase.objects.filter(
                user=request.user,
                status=Purchase.STATUS_PAID,
                article__is_published=True,
            )
            .select_related('article', 'article__category')
            .order_by('-created_at')
        )
        seen = set()
        unique_purchases = []
        for p in purchases:
            if p.article_id not in seen:
                seen.add(p.article_id)
                unique_purchases.append(p)
        serializer = MyPurchasesSerializer(unique_purchases, many=True)
        return Response(serializer.data)


class RazorpayWebhookView(APIView):
    """Provider callbacks. The only unauthenticated write path in the project.

    Signature verification needs the raw bytes, so this must never touch
    `request.data`: DRF would parse the body and the digest would no longer
    match. For the same reason the view carries no authentication classes — a
    JWKS lookup per delivery would be pointless work on an endpoint whose
    authentication is the HMAC.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=None,
        responses={200: None},
        summary='Razorpay webhook (signature-verified, not user-authenticated)',
    )
    def post(self, request):
        if not settings.RAZORPAY_WEBHOOK_SECRET:
            return Response({'detail': PAYMENTS_UNAVAILABLE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        signature = request.headers.get('X-Razorpay-Signature', '')
        event_id = request.headers.get('X-Razorpay-Event-Id', '')
        if not signature or not event_id:
            return Response(
                {'detail': 'Missing signature or event id.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        body = request.body.decode('utf-8')

        try:
            valid = gateway.verify_webhook(body, signature)
        except gateway.PaymentGatewayError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if not valid:
            logger.warning('Rejected Razorpay webhook %s: bad signature', event_id)
            return Response({'detail': 'Invalid signature.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            payload = json.loads(body)
        except ValueError:
            return Response({'detail': 'Malformed payload.'}, status=status.HTTP_400_BAD_REQUEST)

        event_type = payload.get('event', '')

        # Recorded before it is applied, keyed on the event id: Razorpay retries
        # any delivery it could not confirm, and a duplicate must be a no-op.
        event, created = PaymentEvent.objects.get_or_create(
            event_id=event_id,
            defaults={'event_type': event_type, 'payload': payload},
        )
        if not created:
            return Response({'status': 'duplicate'})

        try:
            applied = _apply_event(event_type, payload)
        except Exception:
            # A 500 asks Razorpay to redeliver, and `processed_at` stays null so
            # a stuck delivery is findable instead of invisible.
            logger.exception('Razorpay webhook %s (%s) failed to apply', event_id, event_type)
            return Response({'status': 'error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        event.processed_at = timezone.now()
        event.save(update_fields=['processed_at'])
        return Response({'status': 'ok' if applied else 'ignored'})


def _apply_event(event_type, payload):
    """Apply one delivery. Returns whether it changed anything.

    Unknown event types are acknowledged rather than refused: the endpoint is
    subscribed to a set, and a new event type arriving is not an error.
    """
    body = payload.get('payload') or {}

    if event_type in ('payment.captured', 'payment.failed'):
        payment = (body.get('payment') or {}).get('entity') or {}
        order_id = payment.get('order_id')
        if not order_id:
            return False
        purchase = Purchase.objects.filter(provider_order_id=order_id).first()
        if not purchase:
            # A provider order we never recorded: either a different
            # environment sharing the account, or a purchase deleted here.
            logger.warning('Razorpay %s for unknown order %s', event_type, order_id)
            return False
        if event_type == 'payment.captured':
            settled = purchase.record_payment(payment.get('id', ''))
            # The capture is the only delivery guaranteed to carry the contact
            # the buyer typed, so it is stored even when the row was already
            # settled by the browser's verify call.
            _remember_contact(purchase, payment.get('contact', ''))
            return settled
        return purchase.mark_failed()

    if event_type in ('refund.created', 'refund.processed'):
        refund = (body.get('refund') or {}).get('entity') or {}
        if event_type == 'refund.created':
            # Initiated, not settled: revoking here would lock a reader out for
            # a refund that can still fail.
            return False
        payment_id = refund.get('payment_id')
        if not payment_id:
            return False
        revoked = 0
        for purchase in Purchase.objects.filter(provider_payment_id=payment_id):
            if purchase.mark_refunded():
                revoked += 1
        if revoked:
            logger.info('Refund %s revoked %s purchase(s)', refund.get('id'), revoked)
        return bool(revoked)

    return False


# --- Admin transaction log --------------------------------------------------
#
# These routes read the rows the checkout and webhook paths write. They are
# deliberately read-only: `Purchase.status` is a settlement fact, and the Django
# admin's editable field is the repair hatch for a webhook that never arrived.


def _is_status(value):
    return value in dict(Purchase.STATUS_CHOICES)


class PurchaseLogListView(generics.ListAPIView):
    """Every checkout attempt, for the admin's transaction log."""

    permission_classes = [IsAdminUser]
    serializer_class = PurchaseLogSerializer

    @extend_schema(
        summary='List payment transactions',
        description=(
            'Admin only. `?status=` keeps one of `created`, `paid`, `failed` '
            'or `refunded`; `?search=` matches the buyer, the article, either '
            'provider id, the receipt or the contact number.'
        ),
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Purchase.objects.select_related('user', 'article')
        status_filter = self.request.query_params.get('status', '').strip()
        if _is_status(status_filter):
            queryset = queryset.filter(status=status_filter)

        search = self.request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                Q(user__email__icontains=search)
                | Q(user__username__icontains=search)
                | Q(user__display_name__icontains=search)
                | Q(article__title__icontains=search)
                | Q(article__slug__icontains=search)
                | Q(provider_order_id__icontains=search)
                | Q(provider_payment_id__icontains=search)
                | Q(receipt__icontains=search)
                | Q(contact__icontains=search)
            )

        return queryset.order_by('-created_at', '-id')


class PurchaseSummaryView(APIView):
    """Totals for the transaction log's stat cards."""

    permission_classes = [IsAdminUser]

    @extend_schema(
        responses={200: PurchaseSummarySerializer},
        summary='Summarise payment transactions',
        description='Admin only. Counts and collected/refunded amounts in paise.',
    )
    def get(self, request):
        totals = Purchase.objects.aggregate(
            total=Count('id'),
            paid=Count('id', filter=Q(status=Purchase.STATUS_PAID)),
            paid_amount_paise=Sum(
                'amount_paise', filter=Q(status=Purchase.STATUS_PAID),
            ),
            refunded=Count('id', filter=Q(status=Purchase.STATUS_REFUNDED)),
            refunded_amount_paise=Sum(
                'amount_paise', filter=Q(status=Purchase.STATUS_REFUNDED),
            ),
            failed=Count('id', filter=Q(status=Purchase.STATUS_FAILED)),
            open=Count('id', filter=Q(status=Purchase.STATUS_CREATED)),
        )
        payload = {
            'total': totals['total'] or 0,
            'paid': totals['paid'] or 0,
            'paid_amount_paise': totals['paid_amount_paise'] or 0,
            'refunded': totals['refunded'] or 0,
            'refunded_amount_paise': totals['refunded_amount_paise'] or 0,
            'failed': totals['failed'] or 0,
            'open': totals['open'] or 0,
        }
        return Response(PurchaseSummarySerializer(payload).data)
