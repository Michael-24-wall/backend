# paperless_saas/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from django.views.generic import TemplateView

schema_view = get_schema_view(
    openapi.Info(
        title="Paperless SaaS API",
        default_version='v1',
        description="API documentation for the Multi-Tenant Workflow System. Includes Auth, Documents, and Projects.",
        contact=openapi.Contact(email="support@example.com"),
        license=openapi.License(name="Private License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [
    # Django Admin Interface
    path('admin/', admin.site.urls),

    # API Documentation (Swagger/Redoc)
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),
    path('swagger.json', schema_view.without_ui(cache_timeout=0), name='schema-json'),

    # Core Application APIs
    path('api/', include('core.urls')), 
    path('api/documents/', include('documents.urls')),
    path('api/workflow/', include('workflow.urls')),
    path('api/', include('projects.urls')),
    path('api/dashboard/', include('dashboard.urls')),
    
    path('api/chat/', include('chat.urls')),
    
    path('chat/', TemplateView.as_view(template_name='chat_app.html'), name='chat'),
    path('api/editor/', include('editor.urls')),
]