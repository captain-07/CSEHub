import jwt
from jwt import PyJWKClient
from functools import lru_cache

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.users.models import User


class SupabaseJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    """Teach drf-spectacular about Supabase bearer tokens.

    Without this, the generated schema has no security scheme, so the Swagger UI
    renders without an "Authorize" button and every endpoint looks unauthenticated.
    """

    target_class = 'apps.users.authentication.SupabaseJWTAuthentication'
    name = 'supabaseJwtAuth'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'http',
            'scheme': 'bearer',
            'bearerFormat': 'JWT',
            'description': (
                'Supabase access token. Sign in with Google in the frontend and the '
                'session token is sent as `Authorization: Bearer <token>`. Paste the '
                'access token here to call protected endpoints.'
            ),
        }


class SupabaseJWTAuthentication(BaseAuthentication):

    def authenticate_header(self, request):
        return 'Bearer'

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return None

        try:
            scheme, token = auth_header.split(" ", 1)

            if scheme.lower() != "bearer":
                raise AuthenticationFailed("Invalid authentication scheme")

            if not settings.SUPABASE_URL:
                raise AuthenticationFailed("Authentication is not configured")
            jwks_client = _get_jwks_client(settings.SUPABASE_URL)

            signing_key = jwks_client.get_signing_key_from_jwt(token)

            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
                issuer=f"{settings.SUPABASE_URL}/auth/v1",
            )

            # Keep the verified claims available to views that need more than
            # the user row — `session_id` is what lets a login be recorded once
            # rather than once per request. The signature has already been
            # checked above, so a view can trust these values.
            request.supabase_claims = payload

            supabase_uid = payload.get("sub")

            if not supabase_uid:
                raise AuthenticationFailed("Token missing subject")

            email = payload.get("email", "").strip().lower()
            if not email:
                raise AuthenticationFailed("Token missing email")
            metadata = payload.get('user_metadata') or {}
            requested_name = metadata.get('user_name') or metadata.get('preferred_username')
            superuser_email = getattr(settings, 'DJANGO_SUPERUSER_EMAIL', '').strip().lower()
            is_admin_email = bool(superuser_email and email == superuser_email)

            defaults = {
                "email": email,
                "username": _available_username(requested_name or email, supabase_uid),
                "display_name": metadata.get('full_name') or metadata.get('name') or (requested_name if requested_name != email else ''),
                "avatar_url": metadata.get('avatar_url') or '',
                "is_staff": is_admin_email,
                "is_superuser": is_admin_email,
            }
            user = User.objects.filter(supabase_uid=supabase_uid).first()
            created = False
            if not user:
                # Link pre-existing users created via createsuperuser or seed data
                # who share this email but do not have a Supabase UID assigned yet.
                # The lookup is case-insensitive because `email` is lowercased from
                # the token while a hand-created row may not be; an exact match
                # would miss it and the insert below would duplicate the account.
                existing_by_email = User.objects.filter(email__iexact=email).first()
                if existing_by_email is None:
                    user, created = User.objects.get_or_create(
                        supabase_uid=supabase_uid,
                        defaults=defaults,
                    )
                elif not existing_by_email.supabase_uid:
                    user = existing_by_email
                    user.supabase_uid = supabase_uid
                    user.save(update_fields=['supabase_uid'])
                elif str(existing_by_email.supabase_uid) == str(supabase_uid):
                    # Same identity under a differently-formatted UID string.
                    user = existing_by_email
                else:
                    # The address already belongs to a different Supabase identity.
                    # Creating a row now would violate the unique email constraint
                    # (or silently split the account when only the case differs).
                    raise AuthenticationFailed(
                        'This email is already linked to another sign-in account'
                    )
            if user.is_banned:
                # Enforced on every request rather than only at sign-in: the
                # ban must also stop a token that was issued before the ban.
                raise AuthenticationFailed('This account has been banned')
            if not created:
                # Supabase UID is the stable identity. Keep local email in sync if changed,
                # but preserve user profile customizations (username, display_name, avatar_url).
                changed_fields = []
                if is_admin_email and (not user.is_staff or not user.is_superuser):
                    user.is_staff = True
                    user.is_superuser = True
                    changed_fields.extend(['is_staff', 'is_superuser'])
                if not user.username and requested_name:
                    username = _available_username_for_user(requested_name, supabase_uid, user.pk)
                    user.username = username
                    changed_fields.append('username')
                if user.email != email and not User.objects.exclude(pk=user.pk).filter(email=email).exists():
                    user.email = email
                    changed_fields.append('email')
                avatar_url = metadata.get('avatar_url')
                if avatar_url and not user.avatar_url:
                    user.avatar_url = avatar_url
                    changed_fields.append('avatar_url')
                if changed_fields:
                    user.save(update_fields=changed_fields)

            if not user.is_active:
                raise AuthenticationFailed("User account is disabled")

            return (user, token)

        except AuthenticationFailed:
            raise

        except Exception:
            # Do not reveal JWT/JWKS/provider internals to API clients.
            raise AuthenticationFailed("Invalid or expired authentication token")


@lru_cache(maxsize=4)
def _get_jwks_client(supabase_url):
    return PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def _available_username(candidate, supabase_uid):
    base = ''.join(char for char in str(candidate).split('@')[0] if char.isalnum() or char in '._-')[:141]
    base = base or 'user'
    username = base
    suffix = str(supabase_uid).replace('-', '')[:8]
    if User.objects.filter(username=username).exists():
        username = f'{base[:141]}_{suffix}'
    return username


def _available_username_for_user(candidate, supabase_uid, user_pk):
    username = _available_username(candidate, supabase_uid)
    if username == str(candidate).split('@')[0][:141]:
        return username
    # The requested username may already belong to the same user.
    base = ''.join(char for char in str(candidate).split('@')[0] if char.isalnum() or char in '._-')[:141] or 'user'
    if User.objects.filter(pk=user_pk, username=base).exists():
        return base
    return username
