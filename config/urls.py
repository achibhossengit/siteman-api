from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('api/<str:version>/', include('accounts.urls')),
    path('api/<str:version>/', include('company.urls')),
    path('api/<str:version>/', include('sites.urls')),
    path('api/<str:version>/', include('labours.urls')),
    path('api/<str:version>/', include('activity.urls')),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    from drf_spectacular.views import (
        SpectacularAPIView,
        SpectacularRedocView,
        SpectacularSwaggerView,
    )

    urlpatterns += [
        path('api/schema/', SpectacularAPIView.as_view(api_version='v1'), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
