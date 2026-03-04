from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Game
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
import chess
import chess.pgn
from django.http import HttpResponse

@login_required
def lobby(request):
    waiting_games = Game.objects.filter(status="WAITING").order_by("-created_at")[:20]
    playing_games = Game.objects.filter(status="PLAYING").order_by("-created_at")[:20]
    return render(request, "chess/lobby.html", {
        "waiting_games": waiting_games,
        "playing_games": playing_games,
    })

@login_required
def create_game(request):
    g = Game.objects.create(white=request.user, status="WAITING", fen="startpos")
    return redirect("game", game_id=g.id)

@login_required
def join_game(request, game_id):
    g = get_object_or_404(Game, id=game_id)

    # Can only join waiting games
    if g.status != "WAITING":
        return redirect("game", game_id=g.id)

    # If creator is white, join as black (or vice versa if you want)
    if g.white and g.white != request.user and g.black is None:
        g.black = request.user
        g.status = "PLAYING"
        g.last_move_ts = timezone.now()
        g.save()
    return redirect("game", game_id=g.id)

@login_required
def game_page(request, game_id):
    g = get_object_or_404(Game, id=game_id)

    is_white = (g.white_id == request.user.id)
    is_black = (g.black_id == request.user.id)
    is_player = is_white or is_black

    # only players can stay (simple rule)
    if not is_player:
        return redirect("lobby")

    context = {
        "game": g,
        "white_name": g.white.username if g.white else "—",
        "black_name": g.black.username if g.black else "—",
        "role": "white" if is_white else "black",
        "is_player": is_player,
    }
    return render(request, "chess/game.html", context)

@login_required
def lobby_state(request):
    waiting = list(
        Game.objects.filter(status="WAITING")
        .order_by("-created_at")
        .values("id", "white__username")
    )
    playing = list(
        Game.objects.filter(status="PLAYING")
        .order_by("-created_at")
        .values("id", "white__username", "black__username")
    )
    return JsonResponse({"waiting": waiting, "playing": playing})

@login_required
@require_POST
def delete_game(request, game_id):
    g = get_object_or_404(Game, id=game_id)

    # Only creator (white) can delete, and only if still waiting
    if g.status == "WAITING" and g.white_id == request.user.id:
        g.delete()
        messages.success(request, "Game deleted.")
    else:
        messages.error(request, "You cannot delete this game.")

    return redirect("lobby")


@login_required
def my_games(request):
    games = Game.objects.filter(Q(white=request.user) | Q(black=request.user)).order_by("-created_at")[:50]
    return render(request, "chess/history.html", {"games": games})


def _pgn_result_from_game(g: Game) -> str:
    """
    PGN Result values:
    - "1-0" white win
    - "0-1" black win
    - "1/2-1/2" draw
    - "*" unknown/ongoing
    """
    if g.status != "FINISHED":
        return "*"

    r = (g.result or "").lower()

    if "draw" in r:
        return "1/2-1/2"
    if "white wins" in r:
        return "1-0"
    if "black wins" in r:
        return "0-1"

    # fallback
    return "*"


@login_required
def download_pgn(request, game_id: int):
    g = get_object_or_404(Game, id=game_id)

    # Only players can download (simple rule)
    if not (g.white_id == request.user.id or g.black_id == request.user.id):
        return HttpResponse("Not allowed", status=403)

    board = chess.Board() if g.fen == "startpos" else chess.Board()  # start from initial position

    # Build PGN game
    pgn_game = chess.pgn.Game()
    pgn_game.headers["Event"] = "Django Chess"
    pgn_game.headers["Site"] = request.get_host()
    pgn_game.headers["Date"] = g.created_at.strftime("%Y.%m.%d") if g.created_at else "????.??.??"
    pgn_game.headers["White"] = g.white.username if g.white else "White"
    pgn_game.headers["Black"] = g.black.username if g.black else "Black"
    pgn_game.headers["Result"] = _pgn_result_from_game(g)

    node = pgn_game

    moves = [m for m in (g.moves or "").split(" ") if m.strip()]
    for uci in moves:
        try:
            mv = chess.Move.from_uci(uci)
        except Exception:
            break
        if mv not in board.legal_moves:
            break
        board.push(mv)
        node = node.add_variation(mv)

    # If game finished, also set board result (helps some viewers)
    pgn_game.headers["Result"] = _pgn_result_from_game(g)

    pgn_text = str(pgn_game)

    filename = f"game_{g.id}.pgn"
    resp = HttpResponse(pgn_text, content_type="application/x-chess-pgn; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp