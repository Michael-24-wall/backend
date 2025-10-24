from rest_framework import serializers
from .models import DocumentTemplate, Document, DigitalSignatureLog, DocumentComment, DocumentVersion, DocumentPermission, DocumentShare
from core.serializers import SimpleUserSerializer 
from django.db import transaction
from django.utils import timezone

# --- 1. Document Template Serializer ---
class DocumentTemplateSerializer(serializers.ModelSerializer):
    created_by = SimpleUserSerializer(read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    documents_count = serializers.SerializerMethodField()

    class Meta:
        model = DocumentTemplate
        fields = [
            'id', 'name', 'title', 'description', 'content', 'content_template',
            'created_by', 'organization_name', 'documents_count', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'organization_name', 'documents_count', 'created_at', 'updated_at']

    def get_documents_count(self, obj):
        return obj.documents.count()

    def validate_name(self, value):
        """Ensure template name is unique within organization"""
        request = self.context.get('request')
        if request and request.user.organization:
            if DocumentTemplate.objects.filter(
                organization=request.user.organization, 
                name=value
            ).exists():
                if self.instance is None or self.instance.name != value:
                    raise serializers.ValidationError("A template with this name already exists in your organization.")
        return value

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['organization'] = request.user.organization
        validated_data['created_by'] = request.user
        return super().create(validated_data)

# --- 2. Digital Signature Serializer ---
class DigitalSignatureSerializer(serializers.ModelSerializer):
    signer = SimpleUserSerializer(read_only=True)
    signer_email = serializers.EmailField(source='signer.email', read_only=True)
    signer_name = serializers.SerializerMethodField()

    class Meta:
        model = DigitalSignatureLog
        fields = [
            'id', 'document', 'signer', 'signer_email', 'signer_name', 
            'signer_role', 'signed_at', 'content_hash', 'signature_data',
            'signing_reason', 'ip_address', 'is_valid'
        ]
        read_only_fields = [
            'id', 'signer', 'signer_email', 'signer_name', 'signed_at', 
            'is_valid', 'ip_address'
        ]

    def get_signer_name(self, obj):
        return f"{obj.signer.first_name} {obj.signer.last_name}".strip() or obj.signer.email

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['signer'] = request.user
        validated_data['ip_address'] = self.get_client_ip(request)
        return super().create(validated_data)

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

# --- 3. Document Creation Serializer (Write Only) ---
class DocumentCreateSerializer(serializers.ModelSerializer):
    template_id = serializers.PrimaryKeyRelatedField(
        queryset=DocumentTemplate.objects.all(), 
        source='template', 
        write_only=True,
        help_text="The ID of the template to use."
    )
    template_name = serializers.CharField(source='template.name', read_only=True)

    class Meta:
        model = Document
        fields = ['id', 'title', 'template_id', 'template_name', 'final_content', 'status']
        read_only_fields = ['id', 'template_name']

    def validate_template_id(self, template):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if template.organization != request.user.organization:
                raise serializers.ValidationError("Template does not belong to your organization.")
            if not template.is_active:
                raise serializers.ValidationError("This template is not active.")
        return template

    def validate(self, attrs):
        # Set final_content from template if not provided
        if 'final_content' not in attrs or not attrs['final_content']:
            if 'template' in attrs and attrs['template']:
                attrs['final_content'] = attrs['template'].content
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['organization'] = request.user.organization
        validated_data['created_by'] = request.user
        
        document = Document.objects.create(**validated_data)
        return document

# --- 4. Document Update Serializer ---
class DocumentUpdateSerializer(serializers.ModelSerializer):
    status = serializers.ChoiceField(choices=Document.STATUS_CHOICES)

    class Meta:
        model = Document
        fields = ['title', 'final_content', 'status', 'file_description']
        extra_kwargs = {
            'title': {'required': False},
            'final_content': {'required': False},
        }

    def validate_status(self, value):
        """Validate status transitions"""
        instance = getattr(self, 'instance', None)
        if instance and instance.status == Document.STATUS_SIGNED and value != Document.STATUS_SIGNED:
            raise serializers.ValidationError("Cannot change status of a signed document.")
        return value

# --- 5. Document Detail Serializer (Read Only) ---
class DocumentDetailSerializer(serializers.ModelSerializer):
    template = DocumentTemplateSerializer(read_only=True)
    created_by = SimpleUserSerializer(read_only=True)
    signatures = DigitalSignatureSerializer(many=True, read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)
    can_edit = serializers.SerializerMethodField()
    can_sign = serializers.SerializerMethodField()
    file_size_mb = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'status', 'template', 'final_content', 
            'file_attachment', 'file_description', 'file_size', 'file_size_mb',
            'created_by', 'organization_name', 'created_at', 'updated_at', 
            'signatures', 'can_edit', 'can_sign', 'version'
        ]
        read_only_fields = fields

    def get_can_edit(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        return (obj.created_by == request.user and 
                obj.status in [Document.STATUS_DRAFT, Document.STATUS_PENDING_REVIEW])

    def get_can_sign(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # User can sign if they haven't signed already and document is in signable status
        has_signed = obj.signatures.filter(signer=request.user).exists()
        signable_statuses = [Document.STATUS_PENDING_APPROVAL, Document.STATUS_PENDING_FINAL_SIGNATURE]
        return not has_signed and obj.status in signable_statuses

    def get_file_size_mb(self, obj):
        if obj.file_size:
            return round(obj.file_size / (1024 * 1024), 2)
        return None

# --- 6. Document List Serializer (For listing) ---
class DocumentListSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source='template.name', read_only=True)
    created_by_name = serializers.SerializerMethodField()
    signature_count = serializers.SerializerMethodField()
    last_updated = serializers.DateTimeField(source='updated_at', read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'status', 'template_name', 'created_by_name',
            'signature_count', 'created_at', 'last_updated', 'file_attachment'
        ]
        read_only_fields = fields

    def get_created_by_name(self, obj):
        return f"{obj.created_by.first_name} {obj.created_by.last_name}".strip() or obj.created_by.email

    def get_signature_count(self, obj):
        return obj.signatures.count()

# --- 7. Document Share Serializer ---
class DocumentShareSerializer(serializers.Serializer):
    share_with = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="List of user IDs to share with"
    )
    permission_level = serializers.ChoiceField(
        choices=[
            ('view', 'Can View'),
            ('comment', 'Can Comment'), 
            ('edit', 'Can Edit'),
            ('sign', 'Can Sign')
        ],
        default='view'
    )
    expires_at = serializers.DateTimeField(required=False)

    def validate_share_with(self, value):
        if not value:
            raise serializers.ValidationError("At least one user must be specified.")
        return value

    def validate_expires_at(self, value):
        if value and value <= timezone.now():
            raise serializers.ValidationError("Expiration date must be in the future.")
        return value

# --- 8. Document Comment Serializer ---
class DocumentCommentSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = DocumentComment
        fields = ['id', 'document', 'user', 'user_name', 'comment', 'is_internal', 'created_at', 'updated_at']
        read_only_fields = ['id', 'user', 'user_name', 'created_at', 'updated_at']

    def get_user_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.email

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['user'] = request.user
        return super().create(validated_data)

# --- 9. Document Version Serializer ---
class DocumentVersionSerializer(serializers.ModelSerializer):
    created_by = SimpleUserSerializer(read_only=True)

    class Meta:
        model = DocumentVersion
        fields = ['id', 'version_number', 'content', 'changes', 'created_by', 'created_at']
        read_only_fields = fields

# --- 10. Document Permission Serializer ---
class DocumentPermissionSerializer(serializers.ModelSerializer):
    user = SimpleUserSerializer(read_only=True)
    granted_by = SimpleUserSerializer(read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True)

    class Meta:
        model = DocumentPermission
        fields = [
            'id', 'document', 'document_title', 'user', 'role', 
            'permission_type', 'granted_by', 'granted_at', 'expires_at', 'is_active'
        ]
        read_only_fields = ['id', 'granted_by', 'granted_at']

    def create(self, validated_data):
        request = self.context.get('request')
        validated_data['granted_by'] = request.user
        return super().create(validated_data)

# --- 11. Document Statistics Serializer ---
class DocumentStatisticsSerializer(serializers.Serializer):
    total_documents = serializers.IntegerField()
    by_status = serializers.DictField()
    by_template = serializers.ListField()
    recent_activity = serializers.ListField()

# --- 12. Bulk Update Serializer ---
class DocumentBulkUpdateSerializer(serializers.Serializer):
    document_ids = serializers.ListField(
        child=serializers.IntegerField(),
        help_text="List of document IDs to update"
    )
    status = serializers.ChoiceField(
        choices=Document.STATUS_CHOICES,
        help_text="New status for all documents"
    )

    def validate_document_ids(self, value):
        if not value:
            raise serializers.ValidationError("At least one document ID must be provided.")
        if len(value) > 100:
            raise serializers.ValidationError("Cannot update more than 100 documents at once.")
        return value