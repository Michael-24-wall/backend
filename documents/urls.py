# documents/urls.py

from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import DocumentTemplateViewSet, DocumentViewSet

router = DefaultRouter()
router.register(r'templates', DocumentTemplateViewSet, basename='document-template')
router.register(r'instances', DocumentViewSet, basename='document-instance')

urlpatterns = [
    # API endpoints will be: /api/documents/templates/, /api/documents/instances/, etc.
    path('', include(router.urls)), 
]