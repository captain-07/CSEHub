"""Operational endpoints that belong to the project rather than to an app."""

import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


@never_cache
@require_http_methods(['GET', 'HEAD'])
def healthz(request):
    """Liveness for uptime pingers and Render's idle spin-down.

    Deliberately outside `/api/`: it is not part of the product's API surface,
    takes no authentication and exposes nothing but whether the process can
    answer.

    **GET** runs a ``SELECT 1`` because the point is the database *connection*
    — a process that can serve templates but cannot reach Postgres is not
    healthy — while touching a table would make the check depend on the schema
    and turn a migration into an outage report.  A deferred database is
    reported as 503 with a body, not an exception: a monitor should see
    "degraded" and a load balancer should stop sending traffic, and neither
    should receive a Django error page.

    **HEAD** skips the query entirely and returns an empty 200 with the same
    headers.  This is the cheapest possible "is the process alive?" check for
    uptime pingers and Render's idle spin-down: no database round-trip, no
    response body, no serialisation.
    """
    if request.method == 'HEAD':
        return JsonResponse({'status': 'ok'})

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - any driver failure means "not healthy"
        logger.warning('Health check could not reach the database: %s', exc)
        return JsonResponse({'status': 'degraded'}, status=503)
    return JsonResponse({'status': 'ok'})
