# editor/validators.py
import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from typing import List

def validate_cell_references(references: List[str]) -> None:
    """
    Validate that cell references are in proper format (e.g., A1, B2, AA100)
    """
    cell_ref_pattern = r'^[A-Z]{1,3}[1-9]\d*$'
    for ref in references:
        if not re.match(cell_ref_pattern, ref.upper()):
            raise ValidationError(
                _('Invalid cell reference: "%(ref)s". Must be in format like A1, B2, AA100'),
                params={'ref': ref},
            )

def validate_formula_syntax(formula: str) -> None:
    """
    Validate formula syntax and prevent dangerous functions
    """
    if not formula:
        return
    
    # Check for dangerous functions/patterns
    dangerous_patterns = [
        r'\bSYSTEM\b',
        r'\bEXEC\b',
        r'\bIMPORT\b',
        r'\bOPEN\b',
        r'\bFILE\b',
        r'__import__',
        r'eval\s*\(',
        r'exec\s*\(',
        r'compile\s*\(',
    ]
    
    formula_upper = formula.upper()
    for pattern in dangerous_patterns:
        if re.search(pattern, formula_upper):
            raise ValidationError(
                _('Formula contains potentially dangerous function: "%(formula)s"'),
                params={'formula': formula},
            )

def validate_data_size(data_size: int, max_size: int = 10 * 1024 * 1024) -> None:
    """
    Validate that data size doesn't exceed maximum allowed size
    """
    if data_size > max_size:
        raise ValidationError(
            _('Data size (%(size)s bytes) exceeds maximum allowed size (%(max_size)s bytes)'),
            params={'size': data_size, 'max_size': max_size},
        )

def validate_sheet_names(names: List[str]) -> None:
    """
    Validate sheet names for uniqueness and validity
    """
    if len(names) != len(set(names)):
        raise ValidationError(_('Sheet names must be unique'))
    
    for name in names:
        if not name or not isinstance(name, str):
            raise ValidationError(_('Sheet name must be a non-empty string'))
        
        if len(name) > 50:
            raise ValidationError(_('Sheet name too long (maximum 50 characters)'))
        
        # Prevent potentially problematic names
        if name.strip() in ['', 'null', 'undefined', 'None']:
            raise ValidationError(_('Invalid sheet name'))
        
        # Check for invalid characters
        if re.search(r'[\\/*?\[\]]', name):
            raise ValidationError(_('Sheet name contains invalid characters'))

def prevent_malicious_content(text: str) -> None:
    """
    Check for potentially malicious content in text and raise ValidationError if found
    """
    if not text:
        return
    
    malicious_patterns = [
        r'<script.*?>.*?</script>',
        r'javascript:',
        r'vbscript:',
        r'on\w+\s*=',
        r'expression\s*\(',
        r'url\s*\(',
        r'mocha:',
        r'livescript:',
    ]
    
    for pattern in malicious_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            raise ValidationError(_('Content contains potentially malicious code'))
    
    # Check for excessive length (potential DoS)
    if len(text) > 100000:  # 100KB limit for a single field
        raise ValidationError(_('Content too large (maximum 100KB)'))

def validate_file_extension(value):
    """
    Validate file extensions for uploads
    """
    import os
    from django.core.exceptions import ValidationError
    ext = os.path.splitext(value.name)[1]  # Get the extension
    valid_extensions = ['.json', '.csv', '.xlsx', '.xls']
    if not ext.lower() in valid_extensions:
        raise ValidationError(_('Unsupported file extension.'))

def validate_spreadsheet_title(value):
    """
    Validate spreadsheet title
    """
    if not value or not value.strip():
        raise ValidationError(_('Title cannot be empty'))
    
    if len(value.strip()) < 1:
        raise ValidationError(_('Title must be at least 1 character long'))
    
    if len(value) > 255:
        raise ValidationError(_('Title cannot exceed 255 characters'))
    
    # Check for potentially problematic characters
    if re.search(r'[<>:"/\\|?*]', value):
        raise ValidationError(_('Title contains invalid characters'))

def validate_organization_slug(value):
    """
    Validate organization slug format
    """
    if not re.match(r'^[a-z0-9-]+$', value):
        raise ValidationError(
            _('Organization slug can only contain lowercase letters, numbers, and hyphens')
        )
    
    if len(value) < 3:
        raise ValidationError(_('Organization slug must be at least 3 characters long'))
    
    if len(value) > 50:
        raise ValidationError(_('Organization slug cannot exceed 50 characters'))