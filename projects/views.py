from rest_framework import viewsets, status, serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action
from django.shortcuts import get_object_or_404
from django.db import models
from django.utils import timezone
from datetime import timedelta

from .models import Project, Task
from .serializers import ProjectSerializer, TaskSerializer

class ProjectViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows Projects to be created, viewed, edited, or deleted.
    """
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        """
        Filter queryset to only include projects belonging to the user's organization.
        """
        user = self.request.user
        if not user.is_authenticated or not hasattr(user, 'organization') or not user.organization:
            return Project.objects.none()
        
        return Project.objects.filter(organization=user.organization)

    def perform_create(self, serializer):
        """
        Set the organization field automatically from the request user.
        """
        serializer.save(organization=self.request.user.organization)

    # Custom action to get tasks for a specific project
    @action(detail=True, methods=['get'])
    def tasks(self, request, pk=None):
        """Retrieve all tasks for a specific project."""
        project = self.get_object()
        tasks = project.tasks.all()
        serializer = TaskSerializer(tasks, many=True, context={'request': request})
        return Response(serializer.data)

    # Custom action to quickly change a project's status
    @action(detail=True, methods=['post'], url_path='set-status')
    def set_status(self, request, pk=None):
        """Allows quick update of project status."""
        project = self.get_object()
        new_status = request.data.get('status')
        
        # Get valid status choices from model
        valid_statuses = [choice[0] for choice in Project.STATUS_CHOICES]
        
        if new_status not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Valid choices are: {", ".join(valid_statuses)}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        project.status = new_status
        project.save()
        
        return Response(ProjectSerializer(project).data)

    # Additional useful actions
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get project statistics for the organization."""
        user = request.user
        if not user.organization:
            return Response({'error': 'User has no organization'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Total projects
        total_projects = Project.objects.filter(organization=user.organization).count()
        
        # Projects by status
        by_status = list(Project.objects.filter(organization=user.organization)
                        .values('status')
                        .annotate(count=models.Count('id'))
                        .order_by('status'))
        
        # Recent projects
        recent_projects = Project.objects.filter(organization=user.organization)\
                                       .select_related('organization')\
                                       .order_by('-created_at')[:5]
        
        recent_data = []
        for project in recent_projects:
            recent_data.append({
                'id': project.id,
                'name': project.name,
                'status': project.status,
                'created_at': project.created_at.isoformat(),
            })
        
        return Response({
            'total_projects': total_projects,
            'by_status': by_status,
            'recent_projects': recent_data
        })

    @action(detail=True, methods=['get'], url_path='task-count')
    def task_count(self, request, pk=None):
        """Get task count by status for a project."""
        project = self.get_object()
        
        task_stats = list(project.tasks
                         .values('status')
                         .annotate(count=models.Count('id'))
                         .order_by('status'))
        
        total_tasks = project.tasks.count()
        completed_tasks = project.tasks.filter(status='completed').count()
        
        return Response({
            'project_id': project.id,
            'project_name': project.name,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'completion_rate': round((completed_tasks / total_tasks * 100), 2) if total_tasks > 0 else 0,
            'tasks_by_status': task_stats
        })


class TaskViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows Tasks to be created, viewed, edited, or deleted.
    """
    queryset = Task.objects.all()
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options']

    def get_queryset(self):
        """
        Filter queryset to only include tasks belonging to projects within the user's organization.
        """
        user = self.request.user
        if not user.is_authenticated or not hasattr(user, 'organization') or not user.organization:
            return Task.objects.none()

        return Task.objects.filter(project__organization=user.organization).select_related('project', 'assigned_to')
        
    def perform_create(self, serializer):
        """
        Ensure the Task's Project belongs to the user's organization.
        """
        project_id = self.request.data.get('project')
        if not project_id:
            return Response({'error': 'Project field is required.'}, status=status.HTTP_400_BAD_REQUEST)
            
        project = get_object_or_404(
            Project.objects.filter(organization=self.request.user.organization),
            pk=project_id
        )
        
        serializer.save(project=project)

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

    @action(detail=True, methods=['post'], url_path='update-status')
    def update_status(self, request, pk=None):
        """Update task status to any valid status."""
        task = self.get_object()
        new_status = request.data.get('status')
        
        # Get valid status choices from model
        valid_statuses = [choice[0] for choice in Task.STATUS_CHOICES]
        
        if new_status not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Valid choices are: {", ".join(valid_statuses)}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        task.status = new_status
        task.save()
        
        return Response(TaskSerializer(task).data)

    @action(detail=False, methods=['get'])
    def my_tasks(self, request):
        """Get tasks assigned to the current user."""
        user = request.user
        tasks = Task.objects.filter(
            project__organization=user.organization,
            assigned_to=user
        ).select_related('project')
        
        serializer = TaskSerializer(tasks, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def overdue(self, request):
        """Get overdue tasks."""
        user = request.user
        overdue_tasks = Task.objects.filter(
            project__organization=user.organization,
            due_date__lt=timezone.now().date(),
            status__in=['todo', 'in_progress']
        ).select_related('project', 'assigned_to')
        
        serializer = TaskSerializer(overdue_tasks, many=True, context={'request': request})
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='upcoming-deadlines')
    def upcoming_deadlines(self, request):
        """Get tasks with upcoming deadlines (within 7 days)."""
        user = request.user
        seven_days_later = timezone.now().date() + timedelta(days=7)
        
        upcoming_tasks = Task.objects.filter(
            project__organization=user.organization,
            due_date__gte=timezone.now().date(),
            due_date__lte=seven_days_later,
            status__in=['todo', 'in_progress']
        ).select_related('project', 'assigned_to').order_by('due_date')
        
        serializer = TaskSerializer(upcoming_tasks, many=True, context={'request': request})
        return Response(serializer.data)