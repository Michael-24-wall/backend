from rest_framework.routers import DefaultRouter
from django.urls import path, include
from . import views

router = DefaultRouter()
router.register(r'rooms', views.ChatRoomViewSet, basename='chat-room')
router.register(r'messages', views.MessageViewSet, basename='message')
router.register(r'memberships', views.RoomMembershipViewSet, basename='room-membership')
router.register(r'profiles', views.UserProfileViewSet, basename='user-profile')

urlpatterns = [
    path('', include(router.urls)),
    
    # Additional endpoints
    path('stats/', views.ChatStatisticsAPI.as_view(), name='chat-stats'),
    path('search/', views.SearchMessagesAPI.as_view(), name='search-messages'),
    path('rooms-list/', views.ChatRoomListAPI.as_view(), name='chat-rooms-list'),
    path('upload-file/', views.FileUploadAPI.as_view(), name='file-upload'),
]