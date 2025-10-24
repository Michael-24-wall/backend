from rest_framework import serializers
from django.conf import settings
from .models import Project, Task
from core.serializers import SimpleUserSerializer 

User = settings.AUTH_USER_MODEL

class TaskSerializer(serializers.ModelSerializer):
    assigned_to_info = SimpleUserSerializer(source='assigned_to', read_only=True)

    class Meta:
        model = Task
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
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if value.organization != request.user.organization:
                raise serializers.ValidationError("Cannot create a task for a project outside your organization.")
        return value

    def validate_assigned_to(self, value):
        project_id = self.initial_data.get('project')
        
        if not project_id and self.instance:
            project_id = self.instance.project.id
            
        if not project_id:
            raise serializers.ValidationError("Project ID is required to assign a user.")

        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
             raise serializers.ValidationError("Project does not exist.")

        if value and value.organization != project.organization:
            raise serializers.ValidationError("Cannot assign this task to a user outside the project's organization.")
        
        return value


class ProjectSerializer(serializers.ModelSerializer):
    manager_info = SimpleUserSerializer(source='manager', read_only=True)
    task_count = serializers.SerializerMethodField()
    
    # FIX: Change DateField to DateTimeField or handle date conversion
    start_date = serializers.DateTimeField(required=False, allow_null=True)
    end_date = serializers.DateTimeField(required=False, allow_null=True)
    
    class Meta:
        model = Project
        fields = [
            'id', 
            'organization',
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
        return obj.tasks.count()
        
    def validate_manager(self, value):
        request = self.context.get('request')
        if request and request.user.is_authenticated and value:
            if value.organization != request.user.organization:
                 raise serializers.ValidationError("The manager must belong to your organization.")
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            validated_data['organization'] = request.user.organization
        else:
            raise serializers.ValidationError("User organization context missing for Project creation.")
            
        return super().create(validated_data)