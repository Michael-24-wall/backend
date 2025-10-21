# workflow/urls.py
from rest_framework.routers import DefaultRouter
from django.urls import path, include
from .views import ApprovalStepViewSet

router = DefaultRouter()
# Register the viewset with the 'steps' prefix
router.register(r'steps', ApprovalStepViewSet, basename='approval-step')

urlpatterns = [
    # This includes: GET /steps/, GET /steps/{pk}/, and POST /steps/{pk}/action/
    path('', include(router.urls)),
]