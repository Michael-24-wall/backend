# editor/forms.py
from django import forms
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
import re
import json

# Import your models - ADD THE MISSING ENUM CLASSES
from .models import SpreadsheetDocument, Tag, Organization, DocumentCollaborator, DocumentType, DocumentStatus
from .validators import (
    validate_spreadsheet_title, 
    prevent_malicious_content,
    validate_file_extension
)

class SpreadsheetDocumentForm(forms.ModelForm):
    """
    Form for creating and updating spreadsheet documents via traditional Django views.
    Useful for admin interface or template-based views.
    """
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.all(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control'}),
        help_text=_("Select tags for categorizing this document")
    )
    
    class Meta:
        model = SpreadsheetDocument
        fields = [
            'title', 'description', 'document_type', 'status',
            'is_template', 'is_public', 'allow_comments', 'tags'
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter document title'),
                'maxlength': '255'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': _('Enter document description (optional)'),
                'rows': 3
            }),
            'document_type': forms.Select(attrs={'class': 'form-control'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'is_template': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_public': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_comments': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'title': _('Name of the spreadsheet document (1-255 characters)'),
            'is_template': _('Whether this document should be available as a template'),
            'is_public': _('Whether this document is publicly accessible'),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        # Set the choices for the enum fields
        self.fields['document_type'].choices = DocumentType.choices
        self.fields['status'].choices = DocumentStatus.choices
        
        # Filter tags by user's organization
        if self.user and hasattr(self.user, 'organization'):
            self.fields['tags'].queryset = Tag.objects.filter(
                organization=self.user.organization
            )

    def clean_title(self):
        """Validate spreadsheet title"""
        title = self.cleaned_data.get('title')
        validate_spreadsheet_title(title)
        return title

    def clean_description(self):
        """Validate description for malicious content"""
        description = self.cleaned_data.get('description')
        if description:
            prevent_malicious_content(description)
        return description

    def save(self, commit=True):
        """Set the owner before saving"""
        instance = super().save(commit=False)
        if self.user and not instance.pk:  # Only set owner on create
            instance.owner = self.user
            if hasattr(self.user, 'organization'):
                instance.organization = self.user.organization
        
        if commit:
            instance.save()
            self.save_m2m()  # Save many-to-many relationships (tags)
        
        return instance


class SpreadsheetUploadForm(forms.Form):
    """
    Form for uploading spreadsheet files (Excel, CSV, JSON) and converting them
    to the internal spreadsheet format.
    """
    FILE_TYPE_CHOICES = [
        ('excel', 'Excel File (.xlsx, .xls)'),
        ('csv', 'CSV File (.csv)'),
        ('json', 'JSON File (.json)'),
    ]
    
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Enter document title')
        }),
        help_text=_('Name for the new spreadsheet document')
    )
    
    file = forms.FileField(
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': '.xlsx,.xls,.csv,.json'
        }),
        help_text=_('Upload Excel, CSV, or JSON file')
    )
    
    file_type = forms.ChoiceField(
        choices=FILE_TYPE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        help_text=_('Select the file format')
    )
    
    description = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': _('Optional description'),
            'rows': 2
        })
    )
    
    document_type = forms.ChoiceField(
        choices=DocumentType.choices,  # FIXED: Use DocumentType directly
        initial='spreadsheet',
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def clean_title(self):
        """Validate title"""
        title = self.cleaned_data.get('title')
        validate_spreadsheet_title(title)
        return title

    def clean_file(self):
        """Validate uploaded file"""
        uploaded_file = self.cleaned_data.get('file')
        if uploaded_file:
            # Validate file extension
            validate_file_extension(uploaded_file)
            
            # Validate file size (max 10MB)
            max_size = 10 * 1024 * 1024  # 10MB
            if uploaded_file.size > max_size:
                raise ValidationError(
                    _('File size too large. Maximum size is 10MB.')
                )
            
            # Validate file type based on extension
            file_name = uploaded_file.name.lower()
            file_type = self.cleaned_data.get('file_type')
            
            if file_type == 'excel' and not (file_name.endswith('.xlsx') or file_name.endswith('.xls')):
                raise ValidationError(_('Please upload a valid Excel file'))
            elif file_type == 'csv' and not file_name.endswith('.csv'):
                raise ValidationError(_('Please upload a valid CSV file'))
            elif file_type == 'json' and not file_name.endswith('.json'):
                raise ValidationError(_('Please upload a valid JSON file'))
        
        return uploaded_file

    def clean_description(self):
        """Validate description"""
        description = self.cleaned_data.get('description')
        if description:
            prevent_malicious_content(description)
        return description


class SpreadsheetImportForm(forms.Form):
    """
    Form for importing spreadsheet data from external sources or templates.
    """
    IMPORT_SOURCE_CHOICES = [
        ('template', 'From Template'),
        ('url', 'From URL'),
        ('clipboard', 'From Clipboard Data'),
    ]
    
    source_type = forms.ChoiceField(
        choices=IMPORT_SOURCE_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        help_text=_('Select import source type')
    )
    
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Enter document title')
        })
    )
    
    # Template source
    template = forms.ModelChoiceField(
        queryset=SpreadsheetDocument.objects.filter(is_template=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text=_('Select a template to start from')
    )
    
    # URL source
    import_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://example.com/data.csv'
        }),
        help_text=_('URL to import data from (CSV, JSON)')
    )
    
    # Clipboard data
    clipboard_data = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': _('Paste CSV or JSON data here'),
            'rows': 6
        }),
        help_text=_('Paste CSV or JSON data directly')
    )
    
    def clean(self):
        """Validate that at least one source is provided based on source_type"""
        cleaned_data = super().clean()
        source_type = cleaned_data.get('source_type')
        
        if source_type == 'template' and not cleaned_data.get('template'):
            raise ValidationError(_('Please select a template when importing from templates'))
        
        elif source_type == 'url' and not cleaned_data.get('import_url'):
            raise ValidationError(_('Please provide a URL when importing from URL'))
        
        elif source_type == 'clipboard' and not cleaned_data.get('clipboard_data'):
            raise ValidationError(_('Please provide data when importing from clipboard'))
        
        return cleaned_data

    def clean_title(self):
        """Validate title"""
        title = self.cleaned_data.get('title')
        validate_spreadsheet_title(title)
        return title

    def clean_import_url(self):
        """Validate import URL"""
        url = self.cleaned_data.get('import_url')
        if url:
            # Basic URL validation for allowed domains (extend as needed)
            allowed_domains = ['example.com', 'github.com', 'raw.githubusercontent.com']
            if not any(domain in url for domain in allowed_domains):
                raise ValidationError(
                    _('URL domain not allowed for import. Please use trusted sources.')
                )
        return url

    def clean_clipboard_data(self):
        """Validate clipboard data"""
        data = self.cleaned_data.get('clipboard_data')
        if data:
            prevent_malicious_content(data)
            
            # Basic validation for JSON or CSV format
            try:
                # Try to parse as JSON
                json.loads(data)
            except json.JSONDecodeError:
                # If not JSON, assume CSV and do basic validation
                lines = data.strip().split('\n')
                if len(lines) < 1:
                    raise ValidationError(_('Clipboard data appears to be empty'))
        
        return data


class SpreadsheetSettingsForm(forms.ModelForm):
    """
    Form for updating spreadsheet settings and preferences.
    """
    class Meta:
        model = SpreadsheetDocument
        fields = [
            'allow_comments', 'is_public', 'status',
            'document_type', 'tags'
        ]
        widgets = {
            'allow_comments': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_public': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'status': forms.Select(attrs={'class': 'form-control'}),
            'document_type': forms.Select(attrs={'class': 'form-control'}),
            'tags': forms.SelectMultiple(attrs={'class': 'form-control'}),
        }
        help_texts = {
            'allow_comments': _('Allow users to add comments to this spreadsheet'),
            'is_public': _('Make this spreadsheet publicly accessible without authentication'),
            'status': _('Current status of the document'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set the choices for the enum fields
        self.fields['document_type'].choices = DocumentType.choices
        self.fields['status'].choices = DocumentStatus.choices


class CollaborationInvitationForm(forms.Form):
    """
    Form for inviting collaborators to a spreadsheet document.
    """
    PERMISSION_CHOICES = [
        ('view', 'Can View'),
        ('comment', 'Can Comment'),
        ('edit', 'Can Edit'),
        ('manage', 'Can Manage'),
    ]
    
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': _(' collaborator@example.com')
        }),
        help_text=_('Email address of the person to invite')
    )
    
    permission_level = forms.ChoiceField(
        choices=PERMISSION_CHOICES,
        initial='view',
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text=_('Permission level for the collaborator')
    )
    
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': _('Optional personal message'),
            'rows': 3
        }),
        help_text=_('Optional message to include with the invitation')
    )
    
    def clean_message(self):
        """Validate invitation message"""
        message = self.cleaned_data.get('message')
        if message:
            prevent_malicious_content(message)
        return message


class TagForm(forms.ModelForm):
    """
    Form for creating and editing tags.
    """
    class Meta:
        model = Tag
        fields = ['name', 'color', 'organization']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Enter tag name')
            }),
            'color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
                'style': 'width: 80px; height: 38px;'
            }),
            'organization': forms.Select(attrs={'class': 'form-control'}),
        }
        help_texts = {
            'name': _('Name of the tag (will be converted to lowercase)'),
            'color': _('Color code for the tag (hex format)'),
        }

    def clean_name(self):
        """Clean and validate tag name"""
        name = self.cleaned_data.get('name')
        if name:
            name = name.strip().lower()
            if not name:
                raise ValidationError(_('Tag name cannot be empty'))
            
            # Check for duplicate tags in the same organization
            organization = self.cleaned_data.get('organization')
            if organization:
                existing_tag = Tag.objects.filter(
                    name=name,
                    organization=organization
                ).exclude(pk=self.instance.pk if self.instance else None)
                
                if existing_tag.exists():
                    raise ValidationError(
                        _('A tag with this name already exists in your organization.')
                    )
        
        return name

    def clean_color(self):
        """Validate color format"""
        color = self.cleaned_data.get('color')
        if color and not re.match(r'^#[0-9A-Fa-f]{6}$', color):
            raise ValidationError(_('Color must be in hex format (e.g., #FF5733)'))
        return color


class OrganizationForm(forms.ModelForm):
    """
    Form for creating and editing organizations.
    """
    class Meta:
        model = Organization
        fields = ['name', 'slug', 'plan_type', 'storage_limit_mb']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('Organization name')
            }),
            'slug': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': _('organization-slug')
            }),
            'plan_type': forms.Select(attrs={'class': 'form-control'}),
            'storage_limit_mb': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '100',
                'step': '100'
            }),
        }
        help_texts = {
            'slug': _('URL-friendly version of the name (letters, numbers, hyphens only)'),
            'storage_limit_mb': _('Maximum storage allowed for this organization in MB'),
        }

    def clean_slug(self):
        """Validate organization slug"""
        slug = self.cleaned_data.get('slug')
        if slug:
            if not re.match(r'^[a-z0-9-]+$', slug):
                raise ValidationError(
                    _('Slug can only contain lowercase letters, numbers, and hyphens')
                )
            
            # Check for uniqueness
            if Organization.objects.filter(slug=slug).exclude(pk=self.instance.pk if self.instance else None).exists():
                raise ValidationError(_('An organization with this slug already exists'))
        
        return slug


class BulkOperationForm(forms.Form):
    """
    Form for performing bulk operations on multiple documents.
    """
    OPERATION_CHOICES = [
        ('archive', 'Archive Selected'),
        ('unarchive', 'Unarchive Selected'),
        ('delete', 'Delete Selected'),
        ('change_tags', 'Update Tags'),
        ('change_status', 'Update Status'),
    ]
    
    operation = forms.ChoiceField(
        choices=OPERATION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    documents = forms.ModelMultipleChoiceField(
        queryset=SpreadsheetDocument.objects.none(),  # Will be set in __init__
        widget=forms.SelectMultiple(attrs={'class': 'form-control', 'size': '10'})
    )
    
    # Fields for specific operations
    new_tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control'}),
        help_text=_('Select tags to apply to all selected documents')
    )
    
    new_status = forms.ChoiceField(
        choices=DocumentStatus.choices,  # FIXED: Use DocumentStatus directly
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        help_text=_('Select new status for all selected documents')
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.user:
            # Set documents queryset to user's accessible documents
            self.fields['documents'].queryset = SpreadsheetDocument.get_user_documents(self.user)
            
            # Set tags queryset to user's organization tags
            if hasattr(self.user, 'organization'):
                self.fields['new_tags'].queryset = Tag.objects.filter(
                    organization=self.user.organization
                )

    def clean(self):
        """Validate that operation-specific fields are provided when needed"""
        cleaned_data = super().clean()
        operation = cleaned_data.get('operation')
        
        if operation == 'change_tags' and not cleaned_data.get('new_tags'):
            raise ValidationError(_('Please select tags when updating tags'))
        
        if operation == 'change_status' and not cleaned_data.get('new_status'):
            raise ValidationError(_('Please select a status when updating status'))
        
        return cleaned_data


class SearchForm(forms.Form):
    """
    Form for searching spreadsheets.
    """
    query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': _('Search documents...'),
            'aria-label': 'Search'
        })
    )
    
    document_type = forms.ChoiceField(
        choices=[('', 'All Types')] + list(DocumentType.choices),  # FIXED: Use DocumentType directly
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    status = forms.ChoiceField(
        choices=[('', 'All Statuses')] + list(DocumentStatus.choices),  # FIXED: Use DocumentStatus directly
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    tags = forms.ModelMultipleChoiceField(
        queryset=Tag.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-control'})
    )
    
    date_range = forms.ChoiceField(
        choices=[
            ('', 'Any Time'),
            ('today', 'Today'),
            ('week', 'Past Week'),
            ('month', 'Past Month'),
            ('year', 'Past Year'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        
        if self.user and hasattr(self.user, 'organization'):
            self.fields['tags'].queryset = Tag.objects.filter(
                organization=self.user.organization
            )