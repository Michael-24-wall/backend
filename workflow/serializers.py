# workflow/serializers.py
from rest_framework import serializers
from .models import ApprovalStep

class ApprovalStepSerializer(serializers.ModelSerializer):
    """
    Serializer for viewing and updating an ApprovalStep.
    """
    approver_username = serializers.CharField(source='approver.username', read_only=True)
    document_title = serializers.CharField(source='document.title', read_only=True)

    class Meta:
        model = ApprovalStep
        fields = [
            'id', 'document', 'document_title', 'approver', 'approver_username',
            'order', 'status', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['document', 'approver', 'order', 'created_at', 'updated_at']


class ApprovalActionSerializer(serializers.Serializer):
    """
    Serializer used for the POST/PATCH request body to approve or reject a step.
    """
    action = serializers.ChoiceField(
        choices=['approve', 'reject'], 
        help_text="Action to take: 'approve' or 'reject'."
    )
    notes = serializers.CharField(
        required=False, 
        allow_blank=True,
        help_text="Optional notes for the approval or rejection."
    )