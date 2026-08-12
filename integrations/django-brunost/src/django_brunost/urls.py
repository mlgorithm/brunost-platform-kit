from django.urls import path

from .views import judge_callback, leaderboard

urlpatterns = [
    path("judge/callback", judge_callback, name="brunost-judge-callback"),
    path("contests/<str:contest_id>/leaderboard", leaderboard, name="brunost-leaderboard"),
]
