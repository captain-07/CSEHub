/**
 * Razorpay checkout handoff.
 *
 * The server creates the order and states the amount, so the browser never
 * computes money; this module loads the provider's script, opens the sheet with
 * what the server returned, and hands the signed result back for verification.
 *
 * The callback below is not a grant. Razorpay's script is a third-party
 * dependency running in the page, so a tampered or replayed response can make
 * the sheet say "paid" — only `/payments/verify/` checking the HMAC can unlock
 * anything, and the article page reloads from the server's answer rather than
 * trusting this one.
 */

import { apiFetch } from './api.js';
import { showToast } from './toast.js';

const CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js';

// Fetched on the first purchase rather than with the page: most readers never
// press Buy, and this is a third-party script with its own cookies.
let checkoutScript = null;

function loadCheckoutScript() {
  if (typeof window.Razorpay === 'function') return Promise.resolve();
  if (checkoutScript) return checkoutScript;

  checkoutScript = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = CHECKOUT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Cleared so a retry can actually retry, instead of being handed the same
      // rejected promise for the rest of the page's life.
      checkoutScript = null;
      reject(new Error('Could not open the payment window. Check your connection and try again.'));
    };
    document.head.appendChild(script);
  });

  return checkoutScript;
}

/**
 * Opens the payment sheet for one article and settles it on the server.
 *
 * Resolves with `{ status: 'paid' | 'pending' | 'already_owned' | 'dismissed' }`
 * and rejects only when the handoff itself failed (the order could not be
 * created, the script would not load, verification was refused). A dismissed
 * sheet is an answer, not an error: nothing was charged.
 */
export async function buyArticle(article) {
  const order = await apiFetch('/payments/checkout/', {
    method: 'POST',
    body: { slug: article.slug || String(article.id) },
  });

  if (order.already_owned) return { status: 'already_owned' };

  await loadCheckoutScript();

  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (fn, value) => {
      if (settled) return;
      settled = true;
      fn(value);
    };

    const checkout = new window.Razorpay({
      key: order.key_id,
      order_id: order.order_id,
      amount: order.amount,
      currency: order.currency,
      name: order.name,
      description: order.description,
      prefill: order.prefill || {},
      // The light accent: the sheet is always light, whatever the page theme.
      theme: { color: '#27644c' },
      handler: async (response) => {
        try {
          const result = await apiFetch('/payments/verify/', {
            method: 'POST',
            body: {
              razorpay_order_id: response.razorpay_order_id,
              razorpay_payment_id: response.razorpay_payment_id,
              razorpay_signature: response.razorpay_signature,
            },
            // Verification calls the provider from the server, twice; a plain
            // read's 20 s is tight for that.
            timeout: 60_000,
          });
          settle(resolve, { status: result.status || 'paid' });
        } catch (error) {
          settle(reject, error);
        }
      },
      modal: {
        ondismiss: () => settle(resolve, { status: 'dismissed' }),
      },
    });

    checkout.on('payment.failed', (response) => {
      // Razorpay keeps the sheet open so the reader can try another method;
      // only a verified payment may settle, so this stays a notification.
      const reason = response?.error?.description || 'The payment did not go through.';
      showToast(`${reason} You have not been charged.`, { type: 'error', timeout: 8000 });
    });

    checkout.open();
  });
}
