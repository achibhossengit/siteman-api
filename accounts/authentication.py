def jwt_user_authentication_rule(user) -> bool:
    """Return True only for active tenant users with an active company."""
    return (
        user is not None
        and user.is_active
        and not user.is_staff
        and not user.is_superuser
        and user.company is not None
        and user.company.is_active
    )
