from rest_framework import permissions


class IsAuthorOrReadOnly(permissions.BasePermission):
    """Write access is limited to the article's author.

    `IsAdminUser` answers "is this a staff user?", which is necessary but not
    sufficient: on its own it lets any admin edit or delete anyone else's
    article. `AdminWriteOrReadAnyMixin` hides the admin UI controls, and this
    is the layer that stops a client which skips that UI.

    Superusers are deliberately exempt. They are the break-glass account: if
    an article ends up owned by a departed employee, or seeded content is stuck
    under a placeholder author nobody can log in as, somebody still has to be
    able to reach it. Everyone else is limited to what they wrote.
    """

    message = 'You can only modify articles you authored.'

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        user = request.user
        if not (user and user.is_authenticated and user.is_staff):
            return False
        if user.is_superuser:
            return True
        # An article with no author is shared ground: no non-superuser owns it,
        # so denying every write would strand it permanently.
        return obj.author_id is None or obj.author_id == user.pk