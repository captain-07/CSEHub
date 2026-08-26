import jwt
from jwt import PyJWKClient

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from apps.users.models import User


class SupabaseJWTAuthentication(BaseAuthentication):

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return None

        try:
            scheme, token = auth_header.split(" ", 1)

            if scheme.lower() != "bearer":
                raise AuthenticationFailed("Invalid authentication scheme")

            jwks_url = (
                f"{settings.SUPABASE_URL}"
                "/auth/v1/.well-known/jwks.json"
            )

            jwks_client = PyJWKClient(jwks_url)

            signing_key = jwks_client.get_signing_key_from_jwt(token)

            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256"],
                audience="authenticated",
                issuer=f"{settings.SUPABASE_URL}/auth/v1",
            )

            supabase_uid = payload.get("sub")

            if not supabase_uid:
                raise AuthenticationFailed("Token missing subject")

            user, created = User.objects.get_or_create(
                supabase_uid=supabase_uid,
                defaults={
                    "email": payload.get("email", ""),
                },
            )

            if not user.is_active:
                raise AuthenticationFailed("User account is disabled")

            return (user, token)

        except AuthenticationFailed:
            raise

        except Exception as e:
            raise AuthenticationFailed(
                f"Invalid token: {str(e)}"
            )