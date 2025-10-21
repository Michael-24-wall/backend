# editor/serializers.py
from rest_framework import serializers
from .models import SpreadsheetDocument

class SpreadsheetDocumentSerializer(serializers.ModelSerializer):
    """Serializer for creating and loading SpreadsheetDocument metadata."""
    
    # Use owner's username for display purposes
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    
    class Meta:
        model = SpreadsheetDocument
        fields = ['id', 'title', 'owner', 'owner_username', 'created_at', 'updated_at']
        read_only_fields = ['owner']


class SpreadsheetDataSerializer(serializers.Serializer):
    """Serializer for the complex JSON data structure (schema validation only)."""
    # This serializer is used to describe the expected *structure* of the 
    # editor_data field without having to explicitly define every possible key.
    
    # Example fields based on the complex JSON structure expected from a spreadsheet library
    sheets = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of sheet objects containing cell data, formulas, and config."
    )
    app_version = serializers.CharField(max_length=20)
    file_name = serializers.CharField(max_length=255)