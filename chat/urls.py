from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'rooms', views.ChatRoomViewSet, basename='room')
router.register(r'messages', views.MessageViewSet, basename='message')
router.register(r'memberships', views.RoomMembershipViewSet, basename='membership')
router.register(r'profiles', views.UserProfileViewSet, basename='profile')

urlpatterns = [
    path('', include(router.urls)),
    
    # Additional API endpoints
    path('statistics/', views.ChatStatisticsAPI.as_view(), name='chat-statistics'),
    path('search/', views.MessageSearchAPI.as_view(), name='message-search'),
    path('upload/', views.FileUploadAPI.as_view(), name='file-upload'),
    path('presence/', views.UserPresenceAPI.as_view(), name='user-presence'),
    path('user-suggestions/', views.user_suggestions, name='user-suggestions'),
    path('room-suggestions/', views.room_suggestions, name='room-suggestions'),
]