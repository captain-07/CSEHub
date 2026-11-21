from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone


def _new_receipt():
    """A unique receipt id for the provider, under its 40-character cap.

    A field default rather than a view detail, so every writer (checkout, a comp
    granted in the admin, a test) produces the same shape and none of them has
    to remember. `receipt` is unique precisely so a duplicated request cannot
    reuse another attempt's id.
    """
    return f'csehub-{uuid4().hex}'


class Purchase(models.Model):
    """One checkout attempt for one paid article.

    A row exists per *attempt*, not per reader/article: a double-clicked Buy
    button, a payment retried after a failed card and a duplicated webhook
    delivery all resolve to distinct provider orders, and collapsing them into
    one row would make a retry overwrite the order whose payment later lands.

    Access is therefore derived from any row in the `paid` state. It is never a
    boolean on the user or the article, because that flag would drift the moment
    a refund arrives or a webhook is replayed.

    `provider_order_id` is nullable for a manually granted purchase (a comp),
    where no provider order exists; `unique` tolerates multiple NULLs on both
    PostgreSQL and SQLite.
    """

    STATUS_CREATED = 'created'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'
    STATUS_REFUNDED = 'refunded'
    STATUS_CHOICES = [
        (STATUS_CREATED, 'Created'),
        (STATUS_PAID, 'Paid'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_REFUNDED, 'Refunded'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='purchases',
    )
    article = models.ForeignKey(
        'articles.Article',
        on_delete=models.CASCADE,
        related_name='purchases',
    )
    provider = models.CharField(max_length=20, default='razorpay')
    provider_order_id = models.CharField(
        max_length=100, unique=True, null=True, blank=True
    )
    # Indexed because the refund webhook arrives carrying only the payment id
    # and has to find the row it settles.
    provider_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    # Razorpay states amounts in paise. Stored as an integer rather than a
    # decimal because it is the exact unit the provider is told and checked
    # against — no rounding can creep in between the two.
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_CREATED, db_index=True
    )
    # Our own idempotency key, sent to the provider as the order receipt. Unique
    # so a duplicated checkout request can be recognised rather than billed.
    receipt = models.CharField(max_length=100, unique=True, default=_new_receipt)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            # The access check asks exactly this question on every locked page.
            models.Index(fields=['user', 'article', 'status']),
        ]

    def __str__(self):
        return f'{self.user_id}:{self.article_id} {self.status}'

    # The provider reports what happened in two places: the checkout handler's
    # signed response and the webhook, which arrive in either order and may
    # repeat. These three transitions are the only writers of `status` outside
    # the admin, so that ordering cannot produce a different answer depending on
    # which one landed first.

    def record_payment(self, payment_id=''):
        """Settle the attempt as paid. Returns whether anything changed.

        `refunded` is deliberately terminal: if a refund is somehow applied
        before the capture notification, a late `payment.captured` must not
        hand access back to somebody who has already been reimbursed.
        """
        if self.status in (self.STATUS_PAID, self.STATUS_REFUNDED):
            return False
        if payment_id:
            self.provider_payment_id = payment_id
        self.status = self.STATUS_PAID
        self.paid_at = timezone.now()
        self.save(update_fields=['status', 'paid_at', 'provider_payment_id'])
        return True

    def mark_refunded(self):
        """Revoke access. Allowed from `paid`, and from `created` so an
        out-of-order delivery cannot leave an attempt that later settles."""
        if self.status == self.STATUS_REFUNDED:
            return False
        self.status = self.STATUS_REFUNDED
        self.save(update_fields=['status'])
        return True

    def mark_failed(self):
        """A failed payment only ever moves an *open* attempt.

        A late failure notification must not undo a settled purchase, which can
        happen when a reader retries and the first attempt's failure arrives
        after the second attempt's success.
        """
        if self.status != self.STATUS_CREATED:
            return False
        self.status = self.STATUS_FAILED
        self.save(update_fields=['status'])
        return True


class PaymentEvent(models.Model):
    """A webhook delivery, recorded before it is acted on.

    `event_id` is unique so a retried delivery is a no-op instead of a second
    grant — Razorpay retries any delivery it could not confirm. The raw payload
    is kept for audit, and `processed_at` stays null for a delivery that was
    recorded but failed to apply, which is what makes a stuck event findable.
    """

    provider = models.CharField(max_length=20, default='razorpay')
    event_id = models.CharField(max_length=100, unique=True)
    event_type = models.CharField(max_length=60)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f'{self.event_type} ({self.event_id})'
