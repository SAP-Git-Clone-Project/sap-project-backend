from django.contrib import admin
from .models import Reviews

@admin.register(Reviews)
class ReviewsAdmin(admin.ModelAdmin):
    # Columns in the table view
    list_display = ('id', 'version', 'reviewer', 'review_status', 'reviewed_at')
    
    # Filter by status and date
    list_filter = ('review_status', 'reviewed_at')
    
    # Search by Reviewer username or Version ID
    search_fields = ('reviewer__username', 'version__id', 'comments')
    
    # Keep the auto-generated stuff read-only
    readonly_fields = ('id', 'reviewed_at')
    
    # Make the UI cleaner
    ordering = ('-reviewed_at',)