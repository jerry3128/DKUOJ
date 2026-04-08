from django.db import models


class AIHintLog(models.Model):
    # Who & what
    user = models.ForeignKey('judge.Profile', on_delete=models.CASCADE, related_name='ai_hint_logs', db_index=True)
    submission = models.ForeignKey('judge.Submission', on_delete=models.CASCADE, related_name='ai_hint_logs')
    problem = models.ForeignKey('judge.Problem', on_delete=models.CASCADE, related_name='ai_hint_logs', db_index=True)

    # When
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Submission snapshot (resilient to rejudges)
    submission_result = models.CharField(max_length=3, null=True, blank=True)
    submission_date = models.DateTimeField(null=True, blank=True)

    # Result
    success = models.BooleanField(default=False, db_index=True)
    error_message = models.TextField(blank=True, default='')
    hint_text = models.TextField(blank=True, default='')

    # Token usage
    prompt_tokens = models.IntegerField(null=True, blank=True)
    completion_tokens = models.IntegerField(null=True, blank=True)
    total_tokens = models.IntegerField(null=True, blank=True)
    model_name = models.CharField(max_length=100, blank=True, default='')

    # Performance
    response_time_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['user', '-requested_at']),
            models.Index(fields=['problem', '-requested_at']),
        ]
        verbose_name = 'AI hint log'
        verbose_name_plural = 'AI hint logs'

    def __str__(self):
        return f'AIHintLog #{self.id} - {self.user_id} on {self.problem_id}'
