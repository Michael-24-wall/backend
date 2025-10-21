# editor/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

User = get_user_model()

# NOTE: You must have a Project model defined in a 'projects' app 
# If not, remove the ForeignKey and project_id from the serializer/views.
# from projects.models import Project 

class SpreadsheetDocument(models.Model):
    """
    Model to store document metadata and the full, complex JSON state 
    of the interactive spreadsheet editor (including data, formulas, styles).
    """
    title = models.CharField(max_length=255)
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='spreadsheets')
    
    # Placeholder for project linking (assumes you have a Project model)
    # project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True)
    
    # The core data field for the Excel-like content
    editor_data = JSONField(default=dict) 
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Spreadsheet: {self.title} by {self.owner.username}"