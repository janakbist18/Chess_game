from django.urls import path
from .views import (
    create_game,
    join_game,
    game_page,
    lobby_state,
    delete_game,
    my_games,
)
from .views import download_pgn

urlpatterns = [
    path("create/", create_game, name="create_game"),
    path("join/<int:game_id>/", join_game, name="join_game"),
    path("game/<int:game_id>/", game_page, name="game"),

    # lobby enhancements
    path("lobby-state/", lobby_state, name="lobby_state"),
    path("delete/<int:game_id>/", delete_game, name="delete_game"),

    # history page
    path("history/", my_games, name="my_games"),
    path("game/<int:game_id>/pgn/", download_pgn, name="download_pgn"),
]