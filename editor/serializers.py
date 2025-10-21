# editor/serializers.py
from rest_framework import serializers
from django.core.exceptions import ValidationError
from django.utils import timezone
import json
from django.contrib.auth import get_user_model
User = get_user_model()
import re
import hashlib
from typing import Dict, Any, List
import re
from .models import DocumentCollaborator, DocumentComment, Tag, Organization

from .models import SpreadsheetDocument, DocumentVersion, AuditLog, Organization
from .utils import validate_spreadsheet_structure, sanitize_sheet_data, calculate_data_complexity
from .validators import (
    validate_cell_references,
    validate_formula_syntax,
    validate_data_size,
    validate_sheet_names,
    prevent_malicious_content
)

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    """Basic user serializer"""
    class Meta:
        model = User
        fields = ['id', 'username', 'email']
        ref_name = "EditorUserBasic"  # ADDED

class DynamicFieldsModelSerializer(serializers.ModelSerializer):
    """
    A ModelSerializer that takes an additional `fields` argument that
    controls which fields should be displayed.
    """
    def __init__(self, *args, **kwargs):
        # Don't pass the 'fields' arg up to the superclass
        fields = kwargs.pop('fields', None)
        
        # Instantiate the superclass normally
        super().__init__(*args, **kwargs)
        
        if fields is not None:
            # Drop any fields that are not specified in the `fields` argument.
            allowed = set(fields)
            existing = set(self.fields)
            for field_name in existing - allowed:
                self.fields.pop(field_name)

class OwnerSerializer(serializers.ModelSerializer):
    """Serializer for user ownership information"""
    full_name = serializers.CharField(source='get_full_name', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'full_name']
        read_only_fields = ['id', 'username', 'email', 'full_name']
        ref_name = "EditorOwner"  # ADDED

class OrganizationBasicSerializer(serializers.ModelSerializer):  # RENAMED
    """Serializer for organization information"""
    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'plan_type']
        read_only_fields = ['id', 'name', 'slug', 'plan_type']
        ref_name = "EditorOrganizationBasic"  # ADDED

class SpreadsheetDocumentSerializer(DynamicFieldsModelSerializer):
    """Enhanced serializer for SpreadsheetDocument with comprehensive features"""
    
    # Enhanced owner information
    owner_info = OwnerSerializer(source='owner', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    
    # Organization information
    organization_info = OrganizationBasicSerializer(source='organization', read_only=True)  # UPDATED
    
    # Computed fields
    document_size = serializers.SerializerMethodField()
    sheet_count = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()
    last_modified_by_username = serializers.CharField(
        source='last_modified_by.username', 
        read_only=True,
        allow_null=True
    )
    
    # Collaboration fields
    collaborator_count = serializers.SerializerMethodField()
    collaborators_info = OwnerSerializer(
        source='collaborators', 
        many=True, 
        read_only=True
    )
    
    # Versioning fields
    version_count = serializers.SerializerMethodField()
    last_version_date = serializers.SerializerMethodField()
    
    # Status fields
    status_display = serializers.CharField(
        source='get_status_display', 
        read_only=True
    )
    
    # Security fields
    permissions = serializers.SerializerMethodField()
    
    class Meta:
        model = SpreadsheetDocument
        fields = [
            # Basic fields
            'id', 'title', 'description', 'document_type', 'status',
            
            # Ownership fields
            'owner', 'owner_info', 'owner_username', 'last_modified_by', 'last_modified_by_username',
            
            # Organization fields
            'organization', 'organization_info',
            
            # Timestamp fields
            'created_at', 'updated_at', 'last_accessed_at',
            
            # Computed fields
            'document_size', 'sheet_count', 'is_editable', 'collaborator_count',
            'version_count', 'last_version_date',
            
            # Status displays
            'status_display',
            
            # Boolean flags
            'is_template', 'is_archived', 'is_public',
            
            # Collaboration
            'collaborators', 'collaborators_info',
            
            # Metadata
            'tags', 'metadata',
            
            # Security
            'permissions',
            
            # Data field (carefully managed)
            'editor_data'
        ]
        read_only_fields = [
            'id', 'owner', 'owner_info', 'owner_username', 'organization_info',
            'created_at', 'updated_at', 'last_accessed_at', 'document_size',
            'sheet_count', 'is_editable', 'collaborator_count', 'version_count',
            'last_version_date', 'status_display', 'permissions', 'last_modified_by_username'
        ]
        extra_kwargs = {
            'editor_data': {'write_only': True},  # Don't expose in list views
            'title': {
                'min_length': 1,
                'max_length': 255,
                'help_text': 'Document title (1-255 characters)'
            },
            'description': {
                'required': False,
                'allow_blank': True,
                'max_length': 1000,
                'help_text': 'Optional document description'
            }
        }

    def get_document_size(self, obj) -> int:
        """Calculate document size in bytes"""
        if obj.editor_data:
            return len(json.dumps(obj.editor_data))
        return 0

    def get_sheet_count(self, obj) -> int:
        """Count number of sheets in the document"""
        if obj.editor_data and 'sheets' in obj.editor_data:
            return len(obj.editor_data['sheets'])
        return 0

    def get_is_editable(self, obj) -> bool:
        """Check if current user can edit this document"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        
        return obj.can_edit(request.user)

    def get_collaborator_count(self, obj) -> int:
        """Count number of collaborators"""
        return obj.collaborators.count()

    def get_version_count(self, obj) -> int:
        """Count number of versions"""
        return obj.versions.count()

    def get_last_version_date(self, obj):
        """Get date of last version"""
        last_version = obj.versions.order_by('-created_at').first()
        return last_version.created_at if last_version else None

    def get_permissions(self, obj) -> Dict[str, bool]:
        """Get user permissions for this document"""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return {}
        
        return {
            'can_view': obj.can_view(request.user),
            'can_edit': obj.can_edit(request.user),
            'can_share': obj.can_share(request.user),
            'can_delete': obj.can_delete(request.user),
        }

    def validate_title(self, value: str) -> str:
        """Validate document title"""
        if not value.strip():
            raise serializers.ValidationError("Title cannot be empty or whitespace only.")
        
        # Check for potentially malicious content in title
        if prevent_malicious_content(value):
            raise serializers.ValidationError("Title contains invalid characters.")
        
        # Check for uniqueness within user's documents (optional)
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            existing = SpreadsheetDocument.objects.filter(
                owner=request.user,
                title=value,
                is_archived=False
            )
            if self.instance:  # Update operation
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise serializers.ValidationError(
                    "You already have a document with this title. Please choose a different title."
                )
        
        return value.strip()

    def validate_description(self, value: str) -> str:
        """Validate document description"""
        if value and prevent_malicious_content(value):
            raise serializers.ValidationError("Description contains invalid characters.")
        return value

    def validate_editor_data(self, value: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced validation for editor data"""
        if not value:
            return value
        
        # Validate data size
        max_size = 10 * 1024 * 1024  # 10MB
        if not validate_data_size(value, max_size):
            raise serializers.ValidationError(
                f"Document data exceeds maximum size of {max_size} bytes"
            )
        
        # Validate basic structure
        structure_errors = validate_spreadsheet_structure(value)
        if structure_errors:
            raise serializers.ValidationError({
                'editor_data': structure_errors
            })
        
        # Sanitize data to prevent XSS and other attacks
        sanitized_data = sanitize_sheet_data(value)
        
        return sanitized_data

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Global validation across multiple fields"""
        # Add custom validation logic here
        document_type = attrs.get('document_type', getattr(self.instance, 'document_type', None))
        editor_data = attrs.get('editor_data')
        
        if editor_data and document_type:
            # Validate that data matches document type requirements
            pass
        
        # Ensure templates have valid structure
        if attrs.get('is_template', False) and editor_data:
            if not self._is_valid_template_structure(editor_data):
                raise serializers.ValidationError({
                    'editor_data': "Template documents must have a valid template structure"
                })
        
        return attrs

    def _is_valid_template_structure(self, editor_data: Dict[str, Any]) -> bool:
        """Validate template-specific structure requirements"""
        # Implement template validation logic
        if not editor_data.get('sheets'):
            return False
        
        # Add template-specific validation rules
        return True

    def create(self, validated_data: Dict[str, Any]):
        """Enhanced create with additional processing"""
        # Extract many-to-many fields
        collaborators = validated_data.pop('collaborators', [])
        tags = validated_data.pop('tags', [])
        
        # Set additional fields
        validated_data['owner'] = self.context['request'].user
        if 'organization' not in validated_data:
            validated_data['organization'] = self.context['request'].user.organization
        
        # Calculate data complexity
        if validated_data.get('editor_data'):
            validated_data['complexity_score'] = calculate_data_complexity(
                validated_data['editor_data']
            )
        
        instance = super().create(validated_data)
        
        # Set many-to-many relationships
        if collaborators:
            instance.collaborators.set(collaborators)
        if tags:
            instance.tags.set(tags)
        
        return instance

    def update(self, instance, validated_data: Dict[str, Any]):
        """Enhanced update with change tracking"""
        # Track changes for audit logging
        changes = {}
        for field, value in validated_data.items():
            if hasattr(instance, field) and getattr(instance, field) != value:
                changes[field] = {
                    'from': getattr(instance, field),
                    'to': value
                }
        
        # Handle editor_data changes specifically
        if 'editor_data' in validated_data:
            old_data = instance.editor_data
            new_data = validated_data['editor_data']
            
            # Calculate checksum for change detection
            old_checksum = self._calculate_checksum(old_data) if old_data else None
            new_checksum = self._calculate_checksum(new_data) if new_data else None
            
            if old_checksum != new_checksum:
                changes['editor_data'] = {
                    'size_change': len(json.dumps(new_data or {})) - len(json.dumps(old_data or {})),
                    'checksum_changed': True
                }
                
                # Update complexity score
                validated_data['complexity_score'] = calculate_data_complexity(new_data)
        
        # Update last_modified_by
        validated_data['last_modified_by'] = self.context['request'].user
        validated_data['last_accessed_at'] = timezone.now()
        
        instance = super().update(instance, validated_data)
        
        # Create audit log if changes were made
        if changes:
            AuditLog.objects.create(
                document=instance,
                user=self.context['request'].user,
                action='UPDATED',
                details={'changes': changes}
            )
        
        return instance

    def _calculate_checksum(self, data: Dict[str, Any]) -> str:
        """Calculate MD5 checksum for data"""
        return hashlib.md5(
            json.dumps(data, sort_keys=True).encode('utf-8')
        ).hexdigest()

class SpreadsheetDataSerializer(serializers.Serializer):
    """
    Comprehensive serializer for spreadsheet data structure validation.
    Validates the complex JSON data structure from spreadsheet editors.
    """
    
    # Core structure
    sheets = serializers.ListField(
        child=serializers.DictField(),
        required=True,
        allow_empty=False,
        min_length=1,
        max_length=50,  # Reasonable limit
        help_text="List of sheet objects containing cell data, formulas, and configuration."
    )
    
    app_version = serializers.CharField(
        max_length=20,
        required=True,
        help_text="Application version that created this document."
    )
    
    file_name = serializers.CharField(
        max_length=255,
        required=True,
        help_text="Original file name for the document."
    )
    
    # Metadata
    metadata = serializers.DictField(
        required=False,
        default=dict,
        help_text="Additional metadata about the document."
    )
    
    # Settings and configuration
    settings = serializers.DictField(
        required=False,
        default=dict,
        help_text="Document-level settings and configuration."
    )
    
    # Workbook properties
    workbook_properties = serializers.DictField(
        required=False,
        default=dict,
        help_text="Workbook-level properties and settings."
    )
    
    # Custom properties
    custom_properties = serializers.DictField(
        required=False,
        default=dict,
        help_text="Custom properties and user-defined metadata."
    )
    
    # Revision tracking
    revision_id = serializers.CharField(
        max_length=100,
        required=False,
        allow_null=True,
        help_text="Revision identifier for conflict resolution."
    )
    
    # Statistics
    statistics = serializers.DictField(
        required=False,
        default=dict,
        help_text="Document statistics and metrics."
    )

    def validate_sheets(self, value: List[Dict]) -> List[Dict]:
        """Validate individual sheets in the document"""
        if not value:
            raise serializers.ValidationError("At least one sheet is required.")
        
        sheet_names = set()
        for i, sheet in enumerate(value):
            # Validate sheet name
            sheet_name = sheet.get('name', f'Sheet{i+1}')
            if not validate_sheet_names([sheet_name]):
                raise serializers.ValidationError(
                    f"Invalid sheet name: {sheet_name}. Sheet names must be unique and valid."
                )
            
            if sheet_name in sheet_names:
                raise serializers.ValidationError(f"Duplicate sheet name: {sheet_name}")
            sheet_names.add(sheet_name)
            
            # Validate sheet structure
            sheet_errors = self._validate_sheet_structure(sheet, i)
            if sheet_errors:
                raise serializers.ValidationError({
                    f'sheet_{i}': sheet_errors
                })
        
        return value

    def _validate_sheet_structure(self, sheet: Dict, index: int) -> List[str]:
        """Validate the structure of a single sheet"""
        errors = []
        
        # Required fields
        if 'name' not in sheet:
            errors.append("Sheet name is required")
        
        # Validate cells if present
        if 'cells' in sheet:
            cell_errors = self._validate_cells(sheet['cells'])
            if cell_errors:
                errors.extend(cell_errors)
        
        # Validate formulas if present
        if 'formulas' in sheet:
            formula_errors = self._validate_formulas(sheet['formulas'])
            if formula_errors:
                errors.extend(formula_errors)
        
        return errors

    def _validate_cells(self, cells: Dict) -> List[str]:
        """Validate cell data structure"""
        errors = []
        
        if not isinstance(cells, dict):
            return ["Cells must be a dictionary object"]
        
        for cell_ref, cell_data in cells.items():
            # Validate cell reference format
            if not validate_cell_references([cell_ref]):
                errors.append(f"Invalid cell reference: {cell_ref}")
            
            # Validate cell data structure
            if not isinstance(cell_data, dict):
                errors.append(f"Cell data for {cell_ref} must be an object")
                continue
            
            # Validate value types
            if 'value' in cell_data:
                value = cell_data['value']
                if not self._is_valid_cell_value(value):
                    errors.append(f"Invalid cell value type in {cell_ref}: {type(value)}")
        
        return errors

    def _validate_formulas(self, formulas: Dict) -> List[str]:
        """Validate formula syntax and references"""
        errors = []
        
        if not isinstance(formulas, dict):
            return ["Formulas must be a dictionary object"]
        
        for cell_ref, formula in formulas.items():
            # Validate cell reference
            if not validate_cell_references([cell_ref]):
                errors.append(f"Invalid formula cell reference: {cell_ref}")
            
            # Validate formula syntax
            if not validate_formula_syntax(formula):
                errors.append(f"Invalid formula syntax in {cell_ref}: {formula}")
        
        return errors

    def _is_valid_cell_value(self, value) -> bool:
        """Check if cell value is of acceptable type"""
        acceptable_types = (str, int, float, bool, type(None))
        return isinstance(value, acceptable_types)

    def validate_app_version(self, value: str) -> str:
        """Validate application version format"""
        if not re.match(r'^[a-zA-Z0-9._-]+$', value):
            raise serializers.ValidationError(
                "Invalid app version format. Only alphanumeric characters, dots, hyphens, and underscores are allowed."
            )
        return value

    def validate_file_name(self, value: str) -> str:
        """Validate file name for security"""
        if not value.strip():
            raise serializers.ValidationError("File name cannot be empty.")
        
        # Prevent path traversal attacks
        if '..' in value or '/' in value or '\\' in value:
            raise serializers.ValidationError("Invalid file name.")
        
        # Check for potentially malicious extensions
        dangerous_extensions = ['.exe', '.bat', '.cmd', '.sh', '.php', '.py']
        if any(value.lower().endswith(ext) for ext in dangerous_extensions):
            raise serializers.ValidationError("File type not allowed.")
        
        return value.strip()

    def validate_metadata(self, value: Dict) -> Dict:
        """Validate metadata to prevent excessive size"""
        if value and len(json.dumps(value)) > 10000:  # 10KB limit for metadata
            raise serializers.ValidationError("Metadata too large. Maximum size is 10KB.")
        return value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Global validation for the entire spreadsheet data structure"""
        # Calculate and validate total data size
        total_size = len(json.dumps(attrs))
        max_total_size = 15 * 1024 * 1024  # 15MB total
        
        if total_size > max_total_size:
            raise serializers.ValidationError(
                f"Total document size ({total_size} bytes) exceeds maximum allowed ({max_total_size} bytes)"
            )
        
        # Validate cross-sheet references
        self._validate_cross_sheet_references(attrs)
        
        # Ensure data consistency
        self._validate_data_consistency(attrs)
        
        return attrs

    def _validate_cross_sheet_references(self, attrs: Dict[str, Any]):
        """Validate references between sheets"""
        # Implementation depends on your specific cross-sheet reference format
        pass

    def _validate_data_consistency(self, attrs: Dict[str, Any]):
        """Ensure data consistency across the document"""
        # Check for circular references in formulas
        # Validate that all referenced cells exist
        # Ensure consistent data types
        pass

class DocumentVersionSerializer(serializers.ModelSerializer):
    """Serializer for document versions"""
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    data_size = serializers.SerializerMethodField()
    
    class Meta:
        model = DocumentVersion
        fields = [
            'id', 'document', 'version_number', 'version_data', 'created_by',
            'created_by_username', 'created_at', 'checksum', 'data_size',
            'change_description'
        ]
        read_only_fields = [
            'id', 'document', 'version_number', 'created_by', 'created_by_username',
            'created_at', 'checksum', 'data_size'
        ]
        ref_name = "EditorDocumentVersion"  # ADDED

    def get_data_size(self, obj) -> int:
        """Calculate version data size"""
        if obj.version_data:
            return len(json.dumps(obj.version_data))
        return 0

class BulkOperationSerializer(serializers.Serializer):
    """Serializer for bulk operations"""
    OPERATION_CHOICES = [
        ('archive', 'Archive'),
        ('unarchive', 'Unarchive'),
        ('delete', 'Delete'),
        ('change_owner', 'Change Owner'),
        ('add_collaborators', 'Add Collaborators'),
        ('remove_collaborators', 'Remove Collaborators'),
    ]
    
    operation = serializers.ChoiceField(choices=OPERATION_CHOICES)
    document_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1,
        max_length=100  # Prevent too many operations at once
    )
    new_owner_id = serializers.IntegerField(required=False)
    collaborator_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False
    )
    
    def validate_document_ids(self, value):
        """Validate that documents exist and user has permission"""
        request = self.context.get('request')
        if not request:
            return value
        
        # Check that all documents exist and user has access
        accessible_docs = SpreadsheetDocument.objects.filter(
            id__in=value,
            owner=request.user  # Simplified - extend based on your permission system
        ).values_list('id', flat=True)
        
        inaccessible_docs = set(value) - set(accessible_docs)
        if inaccessible_docs:
            raise serializers.ValidationError(
                f"You don't have permission to modify documents: {inaccessible_docs}"
            )
        
        return value

class DashboardMetricsSerializer(serializers.Serializer):
    """Serializer for dashboard metrics response"""
    
    timestamp = serializers.DateTimeField()
    time_range = serializers.CharField()
    
    user_summary = serializers.DictField()
    organization_kpis = serializers.DictField()
    document_analytics = serializers.DictField()
    performance_metrics = serializers.DictField()
    recent_activity = serializers.ListField()
    predictive_insights = serializers.DictField()
    
    data_freshness = serializers.CharField()
    ref_name = "EditorDashboardMetrics"  # ADDED

class SpreadsheetTemplateSerializer(serializers.ModelSerializer):
    """Serializer for spreadsheet templates"""
    
    usage_count = serializers.SerializerMethodField()
    categories = serializers.ListField(
        child=serializers.CharField(max_length=50)
    )
    
    class Meta:
        model = SpreadsheetDocument
        fields = [
            'id', 'title', 'description', 'document_type', 'editor_data',
            'usage_count', 'categories', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'usage_count', 'created_at', 'updated_at']
        ref_name = "EditorSpreadsheetTemplate"  # ADDED
    
    def get_usage_count(self, obj) -> int:
        """Count how many times this template has been used"""
        return SpreadsheetDocument.objects.filter(
            template_source=obj,
            is_template=False
        ).count()

class DocumentCollaboratorSerializer(serializers.ModelSerializer):
    """Serializer for document collaborators"""
    user_info = UserSerializer(source='user', read_only=True)
    added_by_info = UserSerializer(source='added_by', read_only=True)
    
    class Meta:
        model = DocumentCollaborator
        fields = [
            'id', 'document', 'user', 'user_info', 'permission_level',
            'added_at', 'added_by', 'added_by_info', 'expires_at'
        ]
        read_only_fields = ['id', 'added_at', 'added_by']
        ref_name = "EditorDocumentCollaborator"  # ADDED

    def validate(self, attrs):
        """Validate collaborator permissions"""
        # Ensure user doesn't add themselves as collaborator
        request = self.context.get('request')
        if request and attrs.get('user') == request.user:
            raise serializers.ValidationError("You cannot add yourself as a collaborator")
        
        # Check if collaboration already exists
        document = attrs.get('document') or self.instance.document if self.instance else None
        user = attrs.get('user')
        
        if document and user:
            existing = DocumentCollaborator.objects.filter(
                document=document, 
                user=user
            ).exists()
            
            if existing and (not self.instance or self.instance.user != user):
                raise serializers.ValidationError("This user is already a collaborator")
        
        return attrs

class DocumentCommentSerializer(serializers.ModelSerializer):
    """Serializer for document comments"""
    user_info = UserSerializer(source='user', read_only=True)
    
    class Meta:
        model = DocumentComment
        fields = [
            'id', 'document', 'user', 'user_info', 'parent_comment',
            'content', 'cell_reference', 'created_at', 'updated_at', 'is_resolved'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']
        ref_name = "EditorDocumentComment"  # ADDED

    def validate_content(self, value):
        """Validate comment content"""
        if not value.strip():
            raise serializers.ValidationError("Comment content cannot be empty")
        return value

    def validate_cell_reference(self, value):
        """Validate cell reference format"""
        if value and not re.match(r'^[A-Z]{1,3}[1-9]\d*$', value.upper()):
            raise serializers.ValidationError("Invalid cell reference format")
        return value

class OrganizationDetailSerializer(serializers.ModelSerializer):  # RENAMED
    """Serializer for organizations"""
    member_count = serializers.SerializerMethodField()
    document_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Organization
        fields = [
            'id', 'name', 'slug', 'plan_type', 'storage_limit_mb',
            'created_at', 'updated_at', 'member_count', 'document_count'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'member_count', 'document_count']
        ref_name = "EditorOrganizationDetail"  # ADDED

    def get_member_count(self, obj):
        """Get number of organization members"""
        return obj.organization_memberships.count()

    def get_document_count(self, obj):
        """Get number of documents in organization"""
        return obj.spreadsheets.count()

class TagSerializer(serializers.ModelSerializer):
    """Serializer for tags"""
    usage_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Tag
        fields = ['id', 'name', 'color', 'organization', 'created_by', 'created_at', 'usage_count']
        read_only_fields = ['id', 'created_by', 'created_at', 'usage_count']
        ref_name = "EditorTag"  # ADDED

    def get_usage_count(self, obj):
        """Get number of documents using this tag"""
        return obj.spreadsheets.count()

    def validate_name(self, value):
        """Validate tag name"""
        if not value.strip():
            raise serializers.ValidationError("Tag name cannot be empty")
        return value.strip().lower()

    def validate_color(self, value):
        """Validate color format"""
        if not re.match(r'^#[0-9A-Fa-f]{6}$', value):
            raise serializers.ValidationError("Color must be in hex format (e.g., #FF5733)")
        return value