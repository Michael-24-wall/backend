from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'rooms', views.ChatRoomViewSet, basename='chatroom')
router.register(r'messages', views.MessageViewSet, basename='message')
router.register(r'memberships', views.RoomMembershipViewSet, basename='roommembership')
router.register(r'profile', views.UserProfileViewSet, basename='userprofile')

urlpatterns = [
    # Remove the nested 'api/' - this is already handled by the main urls.py
    path('', include(router.urls)),
    path('history/<str:room_name>/', views.MessageHistoryAPI.as_view(), name='message-history'),
    path('simple-rooms/', views.ChatRoomListAPI.as_view(), name='room-list'),
    path('upload/', views.FileUploadAPI.as_view(), name='file-upload'),
    path('statistics/', views.ChatStatisticsAPI.as_view(), name='chat-statistics'),
    path('search/messages/', views.SearchMessagesAPI.as_view(), name='search-messages'),
]