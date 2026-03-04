from django.db import models
from django.contrib.auth.models import User


class Game(models.Model):
    STATUS_CHOICES = [
        ("WAITING", "Waiting"),
        ("PLAYING", "Playing"),
        ("FINISHED", "Finished"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="WAITING")

    white = models.ForeignKey(
        User,
        related_name="white_games",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    black = models.ForeignKey(
        User,
        related_name="black_games",
        null=True,
        blank=True,
        on_delete=models.SET_NULL
    )

    fen = models.TextField(default="startpos")
    moves = models.TextField(default="", blank=True)  # UCI moves separated by spaces

    # --- Chess clock ---
    white_time = models.IntegerField(default=600)  # 10 minutes
    black_time = models.IntegerField(default=600)
    last_move_ts = models.DateTimeField(null=True, blank=True)

    # --- Game result ---
    result = models.CharField(max_length=64, blank=True, default="")

    # --- Draw offer ---
    draw_offered_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="draw_offers",
        on_delete=models.SET_NULL
    )

    def __str__(self):
        return f"Game #{self.id} ({self.status})"