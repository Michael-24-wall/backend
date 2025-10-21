from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.db.models import Count, Q

# Assuming you have a custom permission class for staff/management roles
from core.permissions import IsProjectManagerOrReadOnly, IsOrganizationMember 

from .models import Project, Task
from .serializers import ProjectSerializer, TaskSerializer

class ProjectViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows Projects to be created, viewed, edited, or deleted.
    Enforces multi-tenancy and role-based permissions.
    """
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated, IsOrganizationMember] # Base permission

    def get_permissions(self):
        """
        Custom permissions logic:
        - POST (Create): Requires IsOrganizationMember (to prevent unauthenticated access)
        - PUT/PATCH/DELETE (Update/Destroy): Requires IsProjectManagerOrReadOnly
        """
        if self.action in ['update', 'partial_update', 'destroy']:
            # Only the Project Manager (or higher admin role defined in the permission class) can modify/delete.
            self.permission_classes = [IsAuthenticated, IsProjectManagerOrReadOnly]
        elif self.action in ['list', 'retrieve']:
            # Any authenticated org member can view.
            self.permission_classes = [IsAuthenticated, IsOrganizationMember]
        
        return [permission() for permission in self.permission_classes]


    def get_queryset(self):
        """
        Filter queryset to only include projects belonging to the user's organization.
        """
        user = self.request.user
        if not user.is_authenticated:
            return Project.objects.none()
        
        # Multi-tenancy enforcement
        return Project.objects.filter(
            organization=user.organization
        ).select_related('manager').prefetch_related('tasks')

    def perform_create(self, serializer):
        """
        Set the organization field automatically from the request user.
        (This is also handled in the serializer, but this adds robustness.)
        """
        # The organization is implicitly set in the ProjectSerializer's create method
        serializer.save(
            organization=self.request.user.organization,
            manager=self.request.user # Optionally set the creator as the initial manager
        )

    # Custom action to get tasks for a specific project
    @action(detail=True, methods=['get'])
    def tasks(self, request, pk=None):
        """Retrieve all tasks for a specific project."""
        project = self.get_object() # Ensures project belongs to the user's org
        
        # Further filtering (e.g., status filter) can be added here
        tasks = project.tasks.all()
        
        # Use a list serializer and pass the request context
        serializer = TaskSerializer(tasks, many=True, context={'request': request})
        return Response(serializer.data)

    # Custom action to quickly change a project's status
    @action(detail=True, methods=['post'], url_path='set-status')
    def set_status(self, request, pk=None):
        """Allows quick update of project status (e.g., for completion or hold)."""
        project = self.get_object()
        new_status = request.data.get('status')
        
        if new_status not in dict(Project.STATUS_CHOICES):
            return Response({'error': 'Invalid status provided.'}, status=status.HTTP_400_BAD_REQUEST)

        # Permission check already handled by get_permissions for update actions
        # The 'IsProjectManagerOrReadOnly' permission will execute during get_object()

        project.status = new_status
        project.save(update_fields=['status', 'updated_at'])
        
        return Response(ProjectSerializer(project).data)


class TaskViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows Tasks to be created, viewed, edited, or deleted.
    """
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated, IsOrganizationMember]

    def get_queryset(self):
        """
        Filter queryset to only include tasks belonging to projects 
        within the user's organization.
        """
        user = self.request.user
        if not user.is_authenticated:
            return Task.objects.none()

        # Efficiently filter tasks based on the project's organization
        return Task.objects.filter(
            project__organization=user.organization
        ).select_related('project', 'assigned_to')
        
    def perform_create(self, serializer):
        """
        Ensure the Task's Project belongs to the user's organization.
        (Validation is handled in the serializer, but this is the save point.)
        """
        project_id = self.request.data.get('project')
        # We must manually fetch the project to ensure multi-tenancy access (defense-in-depth)
        project = get_object_or_404(
            Project.objects.filter(organization=self.request.user.organization),
            pk=project_id
        )
        
        serializer.save(project=project) # Save with the validated project instance

    # Custom action to quickly update a task's status
    @action(detail=True, methods=['post'], url_path='complete')
    def complete_task(self, request, pk=None):
        """Marks a task as completed."""
        task = self.get_object() 
        
        if task.status == 'completed':
            return Response({'message': 'Task is already completed.'}, status=status.HTTP_200_OK)
            
        task.status = 'completed'
        task.save()
        
        return Response(TaskSerializer(task).data)