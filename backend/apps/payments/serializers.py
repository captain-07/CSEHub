"""Payment payloads.

Declared rather than inline so drf-spectacular publishes the shapes the events
actually carry, and so the request bodies are validated before any provider call
is made.
"""

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

    def get_category(self, obj):
        cat = obj.article.category
        if not cat:
            return None
        return {'id': cat.id, 'name': cat.name, 'slug': cat.slug}

