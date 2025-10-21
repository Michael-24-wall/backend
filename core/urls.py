# core/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

# 1. IMPORT ALL NECESSARY VIEWSETS
from .views import (
    AuthViewSet, 
    CustomTokenObtainPairView, 
    OrganizationViewSet,
)

router = DefaultRouter()

# 2. REGISTER ALL VIEWSETS
# Registration for Auth endpoints (e.g., /auth/register/, /auth/verify_email/ etc.)
router.register(r'auth', AuthViewSet, basename='auth') 

# Registration for Organization endpoints (e.g., /organization/my_organization/, /organization/send_invitation/ etc.)
router.register(r'organization', OrganizationViewSet, basename='organization') 

urlpatterns = [
    # Include all router-registered endpoints (AuthViewSet, OrganizationViewSet)
    path('', include(router.urls)),
    
    # Add Chat App's REST endpoints here (e.g., if chat/urls.py contains /history/ endpoint)
    # The URL will resolve to /chat/history/
    path('chat/', include('chat.urls')), # <-- ADD THIS LINE
    
    # JWT endpoints only (manually defined)
    path('auth/login/', CustomTokenObtainPairView.as_view(), name='login'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]