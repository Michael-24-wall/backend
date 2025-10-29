# workflow/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DocumentSubmissionViewSet, 
    WorkflowActionViewSet,
    WorkflowManagementViewSet,
    WorkflowChatViewSet,
    WorkflowStatsAPI
)

router = DefaultRouter()
router.register(r'submissions', DocumentSubmissionViewSet, basename='submission')
router.register(r'actions', WorkflowActionViewSet, basename='action')
router.register(r'templates', WorkflowManagementViewSet, basename='template')
router.register(r'chat', WorkflowChatViewSet, basename='chat')

urlpatterns = [
    path('', include(router.urls)),
    path('stats/', WorkflowStatsAPI.as_view(), name='workflow-stats'),
    
    # Additional endpoints
    path('submissions/my-submissions/', 
         DocumentSubmissionViewSet.as_view({'get': 'my_submissions'}), 
         name='my-submissions'),
    path('submissions/submit/', 
         DocumentSubmissionViewSet.as_view({'post': 'submit_request'}), 
         name='submit-request'),
    path('submissions/<int:pk>/progress/', 
         DocumentSubmissionViewSet.as_view({'get': 'submission_progress'}), 
         name='submission-progress'),
    
    path('actions/team-pending/', 
         WorkflowActionViewSet.as_view({'get': 'team_pending'}), 
         name='team-pending'),
    path('actions/<int:pk>/action/', 
         WorkflowActionViewSet.as_view({'post': 'take_action'}), 
         name='take-action'),
    path('actions/<int:pk>/history/', 
         WorkflowActionViewSet.as_view({'get': 'history'}), 
         name='action-history'),
    path('actions/<int:pk>/details/', 
         WorkflowActionViewSet.as_view({'get': 'flow_details'}), 
         name='flow-details'),
    path('actions/<int:pk>/chat-room/', 
         WorkflowActionViewSet.as_view({'get': 'chat_room'}), 
         name='chat-room'),
    
    path('chat/workflow-rooms/', 
         WorkflowChatViewSet.as_view({'get': 'workflow_rooms'}), 
         name='workflow-rooms'),
]