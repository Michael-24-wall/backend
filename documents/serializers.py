# documents/serializers.py (Corrected and Consolidated)

from rest_framework import serializers
from .models import DocumentTemplate, Document, DigitalSignatureLog
# ✅ FIX: Import SimpleUserSerializer from core
from core.serializers import SimpleUserSerializer 
from django.db import transaction
from django.utils import timezone

# --- 1. Document Template Serializer ---
class DocumentTemplateSerializer(serializers.ModelSerializer):
    created_by = SimpleUserSerializer(read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = DocumentTemplate
        fields = ['id', 'title', 'content_template', 'created_by', 'organization_name', 'created_at']
        read_only_fields = ['id', 'created_by', 'organization_name', 'created_at']

# --- 2. Digital Signature Serializer ---
class DigitalSignatureSerializer(serializers.ModelSerializer):
    signer = SimpleUserSerializer(read_only=True)

    class Meta:
        model = DigitalSignatureLog
        fields = ['id', 'document', 'signer', 'signer_role', 'signed_at', 'content_hash']
        read_only_fields = ['id', 'signer', 'signed_at']
        extra_kwargs = {
            'document': {'write_only': True, 'required': False}, 
            'signer_role': {'read_only': True}
        }

# --- 3. Document Creation Serializer (Write Only) ---
class DocumentCreateSerializer(serializers.ModelSerializer):
    template_id = serializers.PrimaryKeyRelatedField(
        queryset=DocumentTemplate.objects.all(), 
        source='template', 
        write_only=True,
        help_text="The ID of the template to use."
    )
    
    class Meta:
        model = Document
        fields = ['id', 'title', 'template_id']
        read_only_fields = ['id']

    def validate_template_id(self, template):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            if template.organization != request.user.organization:
                raise serializers.ValidationError("Template does not belong to your organization.")
        return template

    @transaction.atomic
    def create(self, validated_data):
        request = self.context.get('request')
        
        validated_data['final_content'] = validated_data.get('template').content_template
        validated_data['organization'] = request.user.organization
        validated_data['created_by'] = request.user
        
        document = Document.objects.create(**validated_data)
        return document

# --- 4. Document Detail Serializer (Read Only) ---
class DocumentDetailSerializer(serializers.ModelSerializer):
    template_title = serializers.CharField(source='template.title', read_only=True)
    created_by = SimpleUserSerializer(read_only=True)
    signatures = DigitalSignatureSerializer(many=True, read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 'title', 'status', 'template_title', 'final_content', 
            'file_attachment', 'created_by', 'created_at', 'updated_at', 'signatures'
        ]
        read_only_fields = fields