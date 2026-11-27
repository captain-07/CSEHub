from django.urls import path

from .views import (
    CheckoutView,
    MyPurchasesView,
    PurchaseLogListView,
    PurchaseSummaryView,
    RazorpayWebhookView,
    VerifyPaymentView,
)

urlpatterns = [
    path('payments/checkout/', CheckoutView.as_view(), name='payment-checkout'),
    path('payments/verify/', VerifyPaymentView.as_view(), name='payment-verify'),
    path('payments/my-purchases/', MyPurchasesView.as_view(), name='my-purchases'),
    # Admin transaction log.
    path('payments/purchases/', PurchaseLogListView.as_view(), name='purchase-log'),
    path('payments/purchases/summary/', PurchaseSummaryView.as_view(), name='purchase-summary'),
    # Deliberately its own path: the URL is pasted into the Razorpay dashboard,
    # so it is an interface with a third party and should not move when the
    # application routes are reorganised.
    path('payments/webhook/razorpay/', RazorpayWebhookView.as_view(), name='payment-webhook-razorpay'),
]
