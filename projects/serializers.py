from rest_framework import serializers
from django.conf import settings
from .models import Project, Task
# Assuming SimpleUserSerializer is available in core.serializers
from core.serializers import SimpleUserSerializer 

User = settings.AUTH_USER_MODEL

# --- 1. Task Serializer (Nested and Detailed) ---
class TaskSerializer(serializers.ModelSerializer):
    # Read-only field for the user assigned to the task
    assigned_to_info = SimpleUserSerializer(source='assigned_to', read_only=True)

    class Meta:
        model = Task
        # organization is inherited via the project, so no need to include it here
        fields = [
            'id', 
            'project', 
            'title', 
            'description', 
            'status', 
            'priority', 
            'due_date',
            'assigned_to', 
            'assigned_to_info',
            'completed_at',
            'created_at'
        ]
        read_only_fields = ['id', 'project', 'assigned_to_info', 'completed_at', 'created_at']

    def validate_project(self, value):
        """
        Ensures the task is being assigned to a project within the user's organization.
        (This security check is primarily handled in the ViewSet queryset, 
         but a serializer check adds defense-in-depth).
        """
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            # Check if the project belongs to the user's primary organization
            if value.organization != request.user.organization:
                raise serializers.ValidationError("Cannot create a task for a project outside your organization.")
        return value

    def validate_assigned_to(self, value):
        """
        Ensures the assigned user belongs to the same organization as the project.
        """
        # If the task is being updated or created, we need the project instance
        project_id = self.initial_data.get('project')
        
        # In case of update, the project field might not be present in initial_data
        if not project_id and self.instance:
            project_id = self.instance.project.id
            
        if not project_id:
            # This should be caught by the required fields, but good for safety
            raise serializers.ValidationError("Project ID is required to assign a user.")

        try:
            # Retrieve the project instance
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
             raise serializers.ValidationError("Project does not exist.")

        if value and value.organization != project.organization:
            raise serializers.ValidationError("Cannot assign this task to a user outside the project's organization.")
        
        return value


# --- 2. Project Serializer (Detailed) ---
class ProjectSerializer(serializers.ModelSerializer):
    # Read-only fields for related data
    manager_info = SimpleUserSerializer(source='manager', read_only=True)
    
    # Nested field to show the task count/list when retrieving a project
    # Use TaskSerializer for nesting if you want the full task details, or Count for summary
    task_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Project
        fields = [
            'id', 
            'organization', # Read-only in practice, set by the view
            'name', 
            'description', 
            'status', 
            'start_date', 
            'end_date',
            'manager', 
            'manager_info',
            'task_count',
            'created_at',
            'updated_at'
        ]
        read_only_fields = ['id', 'organization', 'manager_info', 'task_count', 'created_at', 'updated_at']

    def get_task_count(self, obj):
        """Returns the number of tasks associated with the project."""
        return obj.tasks.count()
        
    def validate_manager(self, value):
        """
        Ensures the project manager belongs to the organization (or is null).
        """
        request = self.context.get('request')
        if request and request.user.is_authenticated and value:
            # When creating a project, the organization is implicitly the user's org
            if value.organization != request.user.organization:
                 raise serializers.ValidationError("The manager must belong to your organization.")
        return value

    def create(self, validated_data):
        """Automatically links the new Project to the creating user's organization."""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['organization'] = request.user.organization
        else:
            # Fallback or strict enforcement if authentication fails
            raise serializers.ValidationError("User organization context missing for Project creation.")
            
        return super().create(validated_data)