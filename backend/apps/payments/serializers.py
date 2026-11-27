"""Payment payloads.

Declared rather than inline so drf-spectacular publishes the shapes the events
actually carry, and so the request bodies are validated before any provider call
is made.
"""

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import Purchase


class CheckoutSerializer(serializers.Serializer):
    slug = serializers.CharField(
        help_text='Slug (or numeric id) of the paid article to buy.'
    )


class VerifyPaymentSerializer(serializers.Serializer):
    """The three values Razorpay's checkout handler hands back.

    Every one of them is a claim until the signature is checked; the view trusts
    none of them on its own.
    """

    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


class CheckoutResponseSerializer(serializers.Serializer):
    """What the browser needs to open Razorpay's sheet.

    The amount and currency are included so the client never computes money: it
    displays what the server already decided to charge.
    """

    already_owned = serializers.BooleanField(
        required=False, help_text='True when access already exists and no order was created.'
    )
    slug = serializers.CharField(required=False)
    purchase_id = serializers.IntegerField(required=False)
    key_id = serializers.CharField(required=False, help_text='Public Razorpay key id.')
    order_id = serializers.CharField(required=False)
    amount = serializers.IntegerField(
        required=False, help_text='Amount in paise, as Razorpay expects it.'
    )
    currency = serializers.CharField(required=False)
    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
    prefill = serializers.DictField(required=False)


class PaymentStatusSerializer(serializers.Serializer):
    status = serializers.CharField(help_text="'paid', 'pending' or 'dismissed'.")
    slug = serializers.CharField(required=False)
    purchase_id = serializers.IntegerField(required=False)
    has_access = serializers.BooleanField(required=False)
    detail = serializers.CharField(required=False)


class PurchasedCategorySerializer(serializers.Serializer):
    """The category a purchased article belongs to. `null` when it has none."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()


class MyPurchasesSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='article.id')
    slug = serializers.CharField(source='article.slug')
    title = serializers.CharField(source='article.title')
    excerpt = serializers.CharField(source='article.excerpt')
    price = serializers.DecimalField(source='article.price', max_digits=8, decimal_places=2)
    category = serializers.SerializerMethodField()
    purchased_at = serializers.DateTimeField(source='created_at')

    class Meta:
        model = Purchase
        fields = ['id', 'slug', 'title', 'excerpt', 'price', 'category', 'purchased_at']

    @extend_schema_field(PurchasedCategorySerializer(allow_null=True))
    def get_category(self, obj):
        cat = obj.article.category
        if not cat:
            return None
        return {'id': cat.id, 'name': cat.name, 'slug': cat.slug}


class PurchaseLogSerializer(serializers.ModelSerializer):
    """One checkout attempt, as the admin transaction log shows it.

    Both the exact `amount_paise` (what the provider was told) and a formatted
    `amount` (what a human reads) are published: the client should not have to
    re-derive money from an integer, and the integer must not be lost to
    rounding on the way out.
    """

    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_display_name = serializers.CharField(source='user.display_name', read_only=True)
    article_id = serializers.IntegerField(source='article.id', read_only=True)
    article_title = serializers.CharField(source='article.title', read_only=True)
    article_slug = serializers.CharField(source='article.slug', read_only=True)
    amount = serializers.SerializerMethodField()

    class Meta:
        model = Purchase
        fields = [
            'id', 'user_id', 'user_email', 'user_username', 'user_display_name',
            'article_id', 'article_title', 'article_slug',
            'amount_paise', 'amount', 'currency', 'status', 'provider',
            'provider_order_id', 'provider_payment_id', 'receipt', 'contact',
            'created_at', 'paid_at',
        ]

    @extend_schema_field(serializers.CharField)
    def get_amount(self, obj):
        return f'{(Decimal(obj.amount_paise) / 100):.2f}'


class PurchaseSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField()
    paid = serializers.IntegerField()
    paid_amount_paise = serializers.IntegerField()
    refunded = serializers.IntegerField()
    refunded_amount_paise = serializers.IntegerField()
    failed = serializers.IntegerField()
    open = serializers.IntegerField()

