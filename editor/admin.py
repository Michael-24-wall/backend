# editor/admin.py
from django.contrib import admin
from .forms import SpreadsheetDocumentForm, TagForm
from .models import SpreadsheetDocument, Tag

@admin.register(SpreadsheetDocument)
class SpreadsheetDocumentAdmin(admin.ModelAdmin):
    form = SpreadsheetDocumentForm  # Use your custom form

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    form = TagForm