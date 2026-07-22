from django.contrib.auth import get_user_model

User = get_user_model()


def get_target_user(request, view):
    """Resolve and cache the parent user for nested ``/users/<user_pk>/...`` routes."""

    if hasattr(request, "_cached_target_user"):
        return request._cached_target_user

    user_pk = view.kwargs.get("user_pk")
    if not user_pk or not getattr(request.user, "is_authenticated", False):
        request._cached_target_user = None
        return None

    if request.user.company_id is None:
        request._cached_target_user = None
        return None

    target = (
        User.objects.filter(
            pk=user_pk,
            company_id=request.user.company_id,
            deleted_at__isnull=True,
        ).first()
    )
    request._cached_target_user = target
    return target
