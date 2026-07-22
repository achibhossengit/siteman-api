from django.contrib.auth import get_user_model
from sites.models import Site

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


def get_target_site(request, view):
    """Resolve and cache the parent site for nested ``/sites/<site_pk>/...`` routes."""

    if hasattr(request, "_cached_target_site"):
        return request._cached_target_site

    site_pk = view.kwargs.get("site_pk")
    if not site_pk or not getattr(request.user, "is_authenticated", False):
        request._cached_target_site = None
        return None

    if request.user.company_id is None:
        request._cached_target_site = None
        return None

    site = Site.objects.filter(
        pk=site_pk,
        company_id=request.user.company_id,
    ).first()
    request._cached_target_site = site
    return site