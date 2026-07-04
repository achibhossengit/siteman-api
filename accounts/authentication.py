
def jwt_user_authentication_rule(user) -> bool:
    """Custom user authentication rule for JWT tokens."""
    return (
        user is not None
        and user.is_active
        and not user.is_staff
        and not user.is_superuser
        and user.company is not None
        and user.company.is_active
    )