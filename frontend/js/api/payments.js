import { apiFetch } from '../api.js';

function toQuery(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, value);
    }
  });
  const serialized = query.toString();
  return serialized ? `?${serialized}` : '';
}

/**
 * Admin transaction log. `filters` accepts `status`
 * (`paid`/`failed`/`refunded`) and `search`.
 */
export function getPurchases(filters, options) {
  return apiFetch(`/payments/purchases/${toQuery(filters)}`, options);
}

/** Totals for the transaction log's stat cards. */
export function getPurchaseSummary(options) {
  return apiFetch('/payments/purchases/summary/', options);
}
