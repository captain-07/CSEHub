from django.contrib import admin

from .models import PaymentEvent, Purchase


@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    """Payment records, with `status` left editable as a repair hatch.

    A webhook that never arrived leaves a purchase stuck in `created` while the
    reader's money has already moved. An operator needs a way to settle that
    without a shell, so `status` stays writable here; everything else that
    proves the payment is read-only from the admin's point of view.
    """

    list_display = [
        'article', 'user', 'status', 'amount_paise', 'provider_order_id',
        'created_at', 'paid_at',
    ]
    list_filter = ['status', 'provider', 'currency']
    search_fields = [
        'article__title', 'user__email', 'provider_order_id',
        'provider_payment_id', 'receipt',
    ]
    list_select_related = ['article', 'user']
    readonly_fields = ['created_at']


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    """Webhook deliveries, readable only.

    The payload is what the provider actually sent; editing it would destroy the
    only evidence of what a disputed delivery contained.
    """

    list_display = ['event_type', 'event_id', 'provider', 'received_at', 'processed_at']
    list_filter = ['event_type', 'provider']
    search_fields = ['event_id', 'event_type']
    readonly_fields = [
        'provider', 'event_id', 'event_type', 'payload', 'received_at', 'processed_at',
    ]

    def has_add_permission(self, request):
        return False
