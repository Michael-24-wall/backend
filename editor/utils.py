# editor/utils.py
import json
import re
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from django.core.exceptions import ValidationError
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def validate_spreadsheet_structure(data: Dict[str, Any]) -> List[str]:
    """
    Validate the basic structure of spreadsheet data.
    Returns a list of error messages, empty if valid.
    """
    errors = []
    
    if not isinstance(data, dict):
        return ["Spreadsheet data must be a JSON object"]
    
    # Required fields validation
    if 'sheets' not in data:
        errors.append("Missing required field: 'sheets'")
    if 'app_version' not in data:
        errors.append("Missing required field: 'app_version'")
    if 'file_name' not in data:
        errors.append("Missing required field: 'file_name'")
    
    if errors:
        return errors
    
    # Sheets validation
    sheets = data.get('sheets', [])
    if not isinstance(sheets, list):
        errors.append("'sheets' must be an array")
        return errors
    
    if len(sheets) == 0:
        errors.append("At least one sheet is required")
    
    if len(sheets) > 50:
        errors.append("Maximum 50 sheets allowed")
    
    # Validate individual sheets
    sheet_names = set()
    for i, sheet in enumerate(sheets):
        if not isinstance(sheet, dict):
            errors.append(f"Sheet {i} must be an object")
            continue
        
        # Sheet name validation
        sheet_name = sheet.get('name', f'Sheet{i+1}')
        if not sheet_name or not isinstance(sheet_name, str):
            errors.append(f"Sheet {i} must have a valid name")
        elif sheet_name in sheet_names:
            errors.append(f"Duplicate sheet name: '{sheet_name}'")
        else:
            sheet_names.add(sheet_name)
        
        # Validate sheet structure
        sheet_errors = _validate_sheet_structure(sheet, i)
        errors.extend(sheet_errors)
    
    # App version validation
    app_version = data.get('app_version', '')
    if not re.match(r'^[a-zA-Z0-9._-]+$', str(app_version)):
        errors.append("Invalid app version format")
    
    # File name validation
    file_name = data.get('file_name', '')
    if not file_name or not isinstance(file_name, str):
        errors.append("Invalid file name")
    elif '..' in file_name or '/' in file_name or '\\' in file_name:
        errors.append("Invalid file name format")
    
    # Metadata size validation
    metadata = data.get('metadata', {})
    if metadata and len(json.dumps(metadata)) > 10000:
        errors.append("Metadata too large (max 10KB)")
    
    return errors

def _validate_sheet_structure(sheet: Dict[str, Any], sheet_index: int) -> List[str]:
    """Validate the structure of a single sheet"""
    errors = []
    
    # Cells validation
    if 'cells' in sheet:
        cells = sheet['cells']
        if not isinstance(cells, dict):
            errors.append(f"Sheet {sheet_index}: 'cells' must be an object")
        else:
            cell_errors = _validate_cells(cells, sheet_index)
            errors.extend(cell_errors)
    
    # Formulas validation
    if 'formulas' in sheet:
        formulas = sheet['formulas']
        if not isinstance(formulas, dict):
            errors.append(f"Sheet {sheet_index}: 'formulas' must be an object")
        else:
            formula_errors = _validate_formulas(formulas, sheet_index)
            errors.extend(formula_errors)
    
    # Styles validation
    if 'styles' in sheet:
        styles = sheet['styles']
        if not isinstance(styles, dict):
            errors.append(f"Sheet {sheet_index}: 'styles' must be an object")
    
    # Config validation
    if 'config' in sheet:
        config = sheet['config']
        if not isinstance(config, dict):
            errors.append(f"Sheet {sheet_index}: 'config' must be an object")
    
    return errors

def _validate_cells(cells: Dict[str, Any], sheet_index: int) -> List[str]:
    """Validate cell data structure"""
    errors = []
    
    for cell_ref, cell_data in cells.items():
        # Validate cell reference format
        if not _is_valid_cell_reference(cell_ref):
            errors.append(f"Sheet {sheet_index}: Invalid cell reference '{cell_ref}'")
            continue
        
        # Validate cell data
        if not isinstance(cell_data, dict):
            errors.append(f"Sheet {sheet_index}: Cell '{cell_ref}' data must be an object")
            continue
        
        # Validate value types
        if 'value' in cell_data:
            value = cell_data['value']
            if not _is_valid_cell_value(value):
                errors.append(f"Sheet {sheet_index}: Invalid value type in cell '{cell_ref}'")
        
        # Validate style reference
        if 'style' in cell_data and not isinstance(cell_data['style'], str):
            errors.append(f"Sheet {sheet_index}: Invalid style reference in cell '{cell_ref}'")
    
    return errors

def _validate_formulas(formulas: Dict[str, Any], sheet_index: int) -> List[str]:
    """Validate formula syntax and references"""
    errors = []
    
    for cell_ref, formula in formulas.items():
        # Validate cell reference
        if not _is_valid_cell_reference(cell_ref):
            errors.append(f"Sheet {sheet_index}: Invalid formula cell reference '{cell_ref}'")
            continue
        
        # Validate formula
        if not isinstance(formula, str):
            errors.append(f"Sheet {sheet_index}: Formula in '{cell_ref}' must be a string")
            continue
        
        # Basic formula syntax validation
        formula_errors = _validate_formula_syntax(formula, cell_ref, sheet_index)
        errors.extend(formula_errors)
    
    return errors

def _is_valid_cell_reference(cell_ref: str) -> bool:
    """Check if cell reference is valid (e.g., A1, B2, AA100)"""
    pattern = r'^[A-Z]{1,3}[1-9]\d*$'
    return bool(re.match(pattern, str(cell_ref).upper()))

def _is_valid_cell_value(value: Any) -> bool:
    """Check if cell value is of acceptable type"""
    acceptable_types = (str, int, float, bool, type(None))
    return isinstance(value, acceptable_types)

def _validate_formula_syntax(formula: str, cell_ref: str, sheet_index: int) -> List[str]:
    """Validate formula syntax (basic checks)"""
    errors = []
    
    # Remove leading = if present
    clean_formula = formula.lstrip('=')
    
    # Check for potentially dangerous functions
    dangerous_functions = ['SYSTEM', 'EXEC', 'IMPORT', 'OPEN', 'FILE']
    for func in dangerous_functions:
        if func in clean_formula.upper():
            errors.append(
                f"Sheet {sheet_index}: Potentially dangerous function in formula at '{cell_ref}'"
            )
    
    # Check for circular references (basic)
    if cell_ref.upper() in clean_formula.upper():
        errors.append(
            f"Sheet {sheet_index}: Possible circular reference in formula at '{cell_ref}'"
        )
    
    # Check formula length
    if len(formula) > 1000:
        errors.append(
            f"Sheet {sheet_index}: Formula too long at '{cell_ref}' (max 1000 characters)"
        )
    
    return errors

def sanitize_sheet_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize spreadsheet data to prevent XSS and other attacks.
    Returns a sanitized copy of the data.
    """
    if not data:
        return {}
    
    # Create a deep copy to avoid modifying original
    sanitized = json.loads(json.dumps(data))
    
    def _sanitize_value(value: Any) -> Any:
        """Recursively sanitize values"""
        if isinstance(value, str):
            # Basic XSS prevention - remove script tags and dangerous attributes
            value = re.sub(r'<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>', '', value, flags=re.IGNORECASE)
            value = re.sub(r'on\w+\s*=', 'data-removed=', value, flags=re.IGNORECASE)
            value = re.sub(r'javascript:', 'data-removed:', value, flags=re.IGNORECASE)
            # Limit string length for cell values
            if len(value) > 10000:
                value = value[:10000]
        elif isinstance(value, dict):
            return {k: _sanitize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [_sanitize_value(item) for item in value]
        return value
    
    return _sanitize_value(sanitized)

def calculate_data_complexity(data: Dict[str, Any]) -> float:
    """
    Calculate a complexity score for spreadsheet data.
    Higher scores indicate more complex spreadsheets.
    """
    if not data:
        return 0.0
    
    complexity = 0.0
    
    try:
        # Factor 1: Number of sheets
        sheets = data.get('sheets', [])
        complexity += len(sheets) * 0.5
        
        # Factor 2: Number of cells
        total_cells = 0
        for sheet in sheets:
            cells = sheet.get('cells', {})
            total_cells += len(cells)
        complexity += total_cells * 0.01
        
        # Factor 3: Number of formulas
        total_formulas = 0
        for sheet in sheets:
            formulas = sheet.get('formulas', {})
            total_formulas += len(formulas)
        complexity += total_formulas * 0.1
        
        # Factor 4: Data variety (different value types)
        value_types = set()
        for sheet in sheets:
            for cell_data in sheet.get('cells', {}).values():
                if 'value' in cell_data:
                    value_type = type(cell_data['value']).__name__
                    value_types.add(value_type)
        complexity += len(value_types) * 0.2
        
        # Factor 5: Nested structures
        data_size = len(json.dumps(data))
        complexity += data_size * 0.000001
        
        # Factor 6: Styles and formatting complexity
        total_styles = 0
        for sheet in sheets:
            styles = sheet.get('styles', {})
            total_styles += len(styles)
        complexity += total_styles * 0.05
        
        # Cap the complexity score
        return min(complexity, 100.0)
        
    except (TypeError, AttributeError, KeyError) as e:
        logger.warning(f"Error calculating data complexity: {e}")
        return 0.0

def validate_data_size(data: Dict[str, Any], max_size: int = 10 * 1024 * 1024) -> bool:
    """Validate that data size doesn't exceed maximum"""
    try:
        data_size = len(json.dumps(data))
        return data_size <= max_size
    except (TypeError, ValueError):
        return False

def calculate_checksum(data: Dict[str, Any]) -> str:
    """Calculate MD5 checksum for data integrity"""
    if not data:
        return ""
    try:
        return hashlib.md5(
            json.dumps(data, sort_keys=True).encode('utf-8')
        ).hexdigest()
    except (TypeError, ValueError):
        return ""

def extract_spreadsheet_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract statistics from spreadsheet data"""
    if not data:
        return {}
    
    stats = {
        'sheet_count': 0,
        'total_cells': 0,
        'formula_count': 0,
        'data_types': set(),
        'total_size': 0,
    }
    
    try:
        sheets = data.get('sheets', [])
        stats['sheet_count'] = len(sheets)
        
        for sheet in sheets:
            # Cell count
            cells = sheet.get('cells', {})
            stats['total_cells'] += len(cells)
            
            # Formula count
            formulas = sheet.get('formulas', {})
            stats['formula_count'] += len(formulas)
            
            # Data types
            for cell_data in cells.values():
                if 'value' in cell_data:
                    value_type = type(cell_data['value']).__name__
                    stats['data_types'].add(value_type)
        
        # Convert set to list for JSON serialization
        stats['data_types'] = list(stats['data_types'])
        
        # Calculate total size
        stats['total_size'] = len(json.dumps(data))
        
    except (TypeError, AttributeError, KeyError) as e:
        logger.warning(f"Error extracting spreadsheet stats: {e}")
    
    return stats

def compress_spreadsheet_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compress spreadsheet data by removing empty values and optimizing structure.
    """
    if not data:
        return {}
    
    def _compress_value(value: Any) -> Any:
        """Recursively compress values"""
        if value is None:
            return None
        elif isinstance(value, dict):
            compressed = {}
            for k, v in value.items():
                compressed_v = _compress_value(v)
                if compressed_v is not None:
                    compressed[k] = compressed_v
            return compressed if compressed else None
        elif isinstance(value, list):
            compressed = [_compress_value(item) for item in value]
            compressed = [item for item in compressed if item is not None]
            return compressed if compressed else None
        elif isinstance(value, str) and not value.strip():
            return None
        else:
            return value
    
    return _compress_value(data) or {}

def validate_cell_references(references: List[str]) -> bool:
    """Validate a list of cell references"""
    for ref in references:
        if not _is_valid_cell_reference(ref):
            return False
    return True

def validate_sheet_names(names: List[str]) -> bool:
    """Validate sheet names for uniqueness and validity"""
    if len(names) != len(set(names)):
        return False  # Duplicate names
    
    for name in names:
        if not name or not isinstance(name, str):
            return False
        if len(name) > 50:
            return False
        # Prevent potentially problematic names
        if name in ['', 'null', 'undefined'] or re.match(r'^\d+$', name):
            return False
    
    return True

def prevent_malicious_content(text: str) -> bool:
    """
    Check for potentially malicious content in text.
    Returns True if malicious content is detected.
    """
    if not text:
        return False
    
    malicious_patterns = [
        r'<script.*?>.*?</script>',
        r'javascript:',
        r'vbscript:',
        r'on\w+\s*=',
        r'expression\s*\(',
        r'url\s*\(',
    ]
    
    text_lower = text.lower()
    for pattern in malicious_patterns:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    
    # Check for excessive length (potential DoS)
    if len(text) > 100000:  # 100KB limit for a single field
        return True
    
    return False

def export_to_excel(data: Dict[str, Any], title: str) -> str:
    """
    Mock function for exporting spreadsheet data to Excel.
    In a real implementation, this would use a library like openpyxl or xlsxwriter.
    """
    # This is a placeholder implementation
    # In production, you would implement actual Excel export logic
    
    logger.info(f"Exporting spreadsheet '{title}' to Excel format")
    
    # Mock file path - in reality, this would generate an actual Excel file
    file_path = f"/tmp/{title}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    # Here you would implement actual Excel export using openpyxl or similar
    # Example:
    # from openpyxl import Workbook
    # wb = Workbook()
    # for sheet_data in data.get('sheets', []):
    #     ws = wb.create_sheet(title=sheet_data.get('name', 'Sheet'))
    #     # Populate worksheet with cell data
    # wb.save(file_path)
    
    return file_path

def backup_document_data(data: Dict[str, Any], document_id: int) -> bool:
    """
    Create a backup of document data.
    In production, this might save to cloud storage or backup system.
    """
    try:
        # Create backup entry or save to backup storage
        backup_info = {
            'document_id': document_id,
            'data': data,
            'backup_timestamp': timezone.now().isoformat(),
            'checksum': calculate_checksum(data),
            'size': len(json.dumps(data))
        }
        
        # In production, you might:
        # 1. Save to a backup database table
        # 2. Upload to cloud storage (S3, etc.)
        # 3. Save to a backup file system
        
        logger.info(f"Backup created for document {document_id}, size: {backup_info['size']} bytes")
        return True
        
    except Exception as e:
        logger.error(f"Backup failed for document {document_id}: {e}")
        return False

def compare_spreadsheet_versions(old_data: Dict[str, Any], new_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compare two versions of spreadsheet data and return differences.
    """
    differences = {
        'sheets_added': [],
        'sheets_removed': [],
        'sheets_modified': [],
        'cells_changed': 0,
        'formulas_changed': 0,
    }
    
    try:
        old_sheets = {sheet.get('name'): sheet for sheet in old_data.get('sheets', [])}
        new_sheets = {sheet.get('name'): sheet for sheet in new_data.get('sheets', [])}
        
        # Find added and removed sheets
        old_sheet_names = set(old_sheets.keys())
        new_sheet_names = set(new_sheets.keys())
        
        differences['sheets_added'] = list(new_sheet_names - old_sheet_names)
        differences['sheets_removed'] = list(old_sheet_names - new_sheet_names)
        
        # Find modified sheets
        common_sheets = old_sheet_names.intersection(new_sheet_names)
        for sheet_name in common_sheets:
            old_sheet = old_sheets[sheet_name]
            new_sheet = new_sheets[sheet_name]
            
            if _sheets_different(old_sheet, new_sheet):
                differences['sheets_modified'].append(sheet_name)
                differences['cells_changed'] += _count_cell_changes(old_sheet, new_sheet)
                differences['formulas_changed'] += _count_formula_changes(old_sheet, new_sheet)
        
    except Exception as e:
        logger.error(f"Error comparing spreadsheet versions: {e}")
    
    return differences

def _sheets_different(sheet1: Dict[str, Any], sheet2: Dict[str, Any]) -> bool:
    """Check if two sheets are different"""
    return (sheet1.get('cells') != sheet2.get('cells') or
            sheet1.get('formulas') != sheet2.get('formulas') or
            sheet1.get('styles') != sheet2.get('styles'))

def _count_cell_changes(sheet1: Dict[str, Any], sheet2: Dict[str, Any]) -> int:
    """Count number of changed cells between two sheets"""
    changes = 0
    cells1 = sheet1.get('cells', {})
    cells2 = sheet2.get('cells', {})
    
    all_cells = set(cells1.keys()) | set(cells2.keys())
    for cell_ref in all_cells:
        if cells1.get(cell_ref) != cells2.get(cell_ref):
            changes += 1
    
    return changes

def _count_formula_changes(sheet1: Dict[str, Any], sheet2: Dict[str, Any]) -> int:
    """Count number of changed formulas between two sheets"""
    changes = 0
    formulas1 = sheet1.get('formulas', {})
    formulas2 = sheet2.get('formulas', {})
    
    all_formulas = set(formulas1.keys()) | set(formulas2.keys())
    for cell_ref in all_formulas:
        if formulas1.get(cell_ref) != formulas2.get(cell_ref):
            changes += 1
    
    return changes
# Add this function to your editor/utils.py file

def validate_spreadsheet_data(data: Dict[str, Any]) -> List[str]:
    """
    Validate spreadsheet data structure and content.
    Returns list of errors, empty list if valid.
    """
    errors = []
    
    # Basic structure validation
    if not isinstance(data, dict):
        return ["Data must be a JSON object"]
    
    # Check for required fields
    required_fields = ['sheets', 'app_version', 'file_name']
    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required field: {field}")
    
    if errors:
        return errors
    
    # Validate sheets structure
    sheets = data.get('sheets', [])
    if not isinstance(sheets, list):
        errors.append("Sheets must be an array")
    elif len(sheets) == 0:
        errors.append("At least one sheet is required")
    elif len(sheets) > 50:
        errors.append("Maximum 50 sheets allowed")
    
    # Validate individual sheets
    sheet_names = set()
    for i, sheet in enumerate(sheets):
        if not isinstance(sheet, dict):
            errors.append(f"Sheet {i} must be an object")
            continue
        
        sheet_name = sheet.get('name', f'Sheet{i+1}')
        if sheet_name in sheet_names:
            errors.append(f"Duplicate sheet name: {sheet_name}")
        sheet_names.add(sheet_name)
    
    # App version validation
    app_version = data.get('app_version', '')
    if not re.match(r'^[a-zA-Z0-9._-]+$', str(app_version)):
        errors.append("Invalid app version format")
    
    # File name validation
    file_name = data.get('file_name', '')
    if not file_name or not isinstance(file_name, str):
        errors.append("Invalid file name")
    elif '..' in file_name or '/' in file_name or '\\' in file_name:
        errors.append("Invalid file name format")
    
    return errors
# Add this function to your editor/utils.py file

def calculate_spreadsheet_stats(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate statistics for spreadsheet data.
    """
    if not data:
        return {}
    
    stats = {
        'sheet_count': 0,
        'total_cells': 0,
        'formula_count': 0,
        'data_size': 0,
        'cell_types': {}
    }
    
    try:
        sheets = data.get('sheets', [])
        stats['sheet_count'] = len(sheets)
        stats['data_size'] = len(json.dumps(data))
        
        for sheet in sheets:
            # Count cells
            cells = sheet.get('cells', {})
            stats['total_cells'] += len(cells)
            
            # Count formulas
            formulas = sheet.get('formulas', {})
            stats['formula_count'] += len(formulas)
            
            # Analyze cell types
            for cell_data in cells.values():
                if isinstance(cell_data, dict) and 'value' in cell_data:
                    value_type = type(cell_data['value']).__name__
                    stats['cell_types'][value_type] = stats['cell_types'].get(value_type, 0) + 1
        
    except (TypeError, AttributeError):
        pass
    
    return stats