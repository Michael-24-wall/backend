from django.db import models
from django.conf import settings
from core.models import Organization # Assuming Organization model is in core/models.py
from django.utils import timezone
from datetime import timedelta

# Get the custom user model
User = settings.AUTH_USER_MODEL

class Project(models.Model):
    """
    Represents a multi-tenant project within an organization.
    """
    STATUS_CHOICES = [
        ('planning', 'Planning'),
        ('active', 'Active'),
        ('on_hold', 'On Hold'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    # --- Multi-tenancy Link ---
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE, 
        related_name='projects',
        help_text="The organization this project belongs to."
    )

    # --- Core Fields ---
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='planning'
    )
    
    # --- Dates and Tracking ---
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    
    # --- Project Management ---
    manager = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='managed_projects'
    )
    
    # --- Metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Ensures no two projects have the same name within the same organization
        unique_together = ('organization', 'name')
        ordering = ['status', 'end_date']
        verbose_name = "Project"
        verbose_name_plural = "Projects"

    def __str__(self):
        return f"{self.organization.name} - {self.name} ({self.status})"

    def is_overdue(self):
        """Checks if the project is past its due date and not completed."""
        return self.end_date and self.end_date < timezone.now().date() and self.status not in ['completed', 'cancelled']

class Task(models.Model):
    """
    Represents an individual task belonging to a project.
    """
    STATUS_CHOICES = [
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('review', 'Review'),
        ('completed', 'Completed'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]

    # --- Links ---
    project = models.ForeignKey(
        Project, 
        on_delete=models.CASCADE, 
        related_name='tasks'
    )
    assigned_to = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='assigned_tasks'
    )

    # --- Core Fields ---
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='todo'
    )
    priority = models.CharField(
        max_length=10, 
        choices=PRIORITY_CHOICES, 
        default='medium'
    )

    # --- Dates and Tracking ---
    due_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # --- Metadata ---
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['due_date', 'priority']
        verbose_name = "Task"
        verbose_name_plural = "Tasks"

    def __str__(self):
        return f"[{self.project.name}] {self.title} ({self.status})"

    def is_overdue(self):
        """Checks if the task is past its due date and not completed."""
        return self.due_date and self.due_date < timezone.now().date() and self.status != 'completed'

    def save(self, *args, **kwargs):
        """Sets completed_at timestamp when status is set to 'completed'."""
        if self.status == 'completed' and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != 'completed' and self.completed_at:
             self.completed_at = None # Clear timestamp if reverted from completed
        super().save(*args, **kwargs)