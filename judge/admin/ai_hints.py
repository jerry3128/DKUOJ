from django.contrib import admin


class AIHintLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'problem', 'submission_result', 'success', 'total_tokens',
                    'response_time_ms', 'requested_at']
    list_filter = ['success', 'requested_at']
    search_fields = ['user__user__username', 'problem__code', 'problem__name']
    date_hierarchy = 'requested_at'
    readonly_fields = ['user', 'submission', 'problem', 'requested_at', 'submission_result',
                       'submission_date', 'success', 'error_message', 'hint_text',
                       'prompt_tokens', 'completion_tokens', 'total_tokens', 'model_name',
                       'response_time_ms']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
