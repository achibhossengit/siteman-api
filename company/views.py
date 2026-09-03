from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import DjangoModelPermissions, IsAuthenticated
from rest_framework.response import Response

from core.permissions import ActiveSubscriptionOrReadOnly
from .models import Company
from .permissions import HasTenantCompany
from .serializers import CompanyDeleteSerializer, CompanySerializer


class CompanyViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Current user's company.

    ``GET /company`` — name, entitlements, and the company site catalog.
    ``PATCH /company`` — name and labour_transfer_allowed (``change_company``).
    ``DELETE /company`` — password-confirmed hard delete (``delete_company``).
    """

    serializer_class = CompanySerializer
    queryset = Company.objects.none()
    permission_classes = [
        IsAuthenticated,
        HasTenantCompany,
        # allow to view the company config without "view_company" permission 
        DjangoModelPermissions,
        ActiveSubscriptionOrReadOnly,
    ]
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_serializer_class(self):
        if self.action == "destroy":
            return CompanyDeleteSerializer
        return CompanySerializer

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated or user.company_id is None:
            return Company.objects.none()
        return Company.objects.filter(pk=user.company_id)

    def get_object(self):
        obj = self.get_queryset().first()
        if obj is None:
            raise NotFound()
        self.check_object_permissions(self.request, obj)
        return obj

    @transaction.atomic
    def perform_update(self, serializer):
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def perform_destroy(self, instance):
        instance.delete()
