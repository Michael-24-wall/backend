# chat/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create router
router = DefaultRouter()
router.register(r'rooms', views.ChatRoomViewSet, basename='chatroom')
router.register(r'messages', views.MessageViewSet, basename='message')
router.register(r'memberships', views.RoomMembershipViewSet, basename='roommembership')
router.register(r'profiles', views.UserProfileViewSet, basename='userprofile')

urlpatterns = [
    # Include router URLs
    path('', include(router.urls)),
    
    # Special API endpoints
    path('statistics/', views.ChatStatisticsAPI.as_view(), name='chat-statistics'),
    path('search/', views.SearchMessagesAPI.as_view(), name='search-messages'),
    path('history/<str:room_name>/', views.MessageHistoryAPI.as_view(), name='message-history'),
    path('user-profile/', views.UserProfileAPI.as_view(), name='user-profile'),
    path('upload/', views.FileUploadAPI.as_view(), name='file-upload'),
    path('rooms-list/', views.ChatRoomListAPI.as_view(), name='chat-rooms-list'),
]