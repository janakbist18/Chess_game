import json
import chess
from django.utils import timezone
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from .models import Game


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if user.is_anonymous:
            await self.close()
            return

        self.game_id = int(self.scope["url_route"]["kwargs"]["game_id"])
        self.room_name = f"game_{self.game_id}"

        game = await self.get_game()
        if not (game.white_id == user.id or game.black_id == user.id):
            await self.close()
            return

        await self.channel_layer.group_add(self.room_name, self.channel_name)
        await self.accept()

        state = await self.get_state()
        await self.send_json({"type": "state", **state})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_name, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            await self.send_json({"type": "error", "message": "Invalid JSON"})
            return

        msg_type = data.get("type")

        # 1) Chess move
        if msg_type == "move":
            uci = data.get("uci")
            ok, payload = await self.apply_move(uci)
            if ok:
                await self.channel_layer.group_send(self.room_name, {
                    "type": "broadcast",
                    "payload": {"type": "state", **payload}
                })
            else:
                await self.send_json({"type": "error", "message": payload})

        # 2) Legal move highlighting
        elif msg_type == "legal_moves":
            frm = data.get("from")
            tos = await self.get_legal_tos(frm)
            await self.send_json({"type": "legal_moves_result", "from": frm, "tos": tos})

        # 3) Chat
        elif msg_type == "chat":
            text = (data.get("text") or "").strip()
            if text:
                name = self.scope["user"].username
                await self.channel_layer.group_send(self.room_name, {
                    "type": "broadcast",
                    "payload": {"type": "chat", "name": name, "text": text[:200]}
                })

        # 4) WebRTC signaling -> relay
        elif msg_type in ("webrtc_offer", "webrtc_answer", "webrtc_ice", "webrtc_hangup"):
            await self.channel_layer.group_send(self.room_name, {
                "type": "broadcast",
                "payload": data
            })

        # 5) Resign
        elif msg_type == "resign":
            ok, payload = await self.resign_game()
            if ok:
                await self.channel_layer.group_send(self.room_name, {
                    "type": "broadcast",
                    "payload": {"type": "state", **payload}
                })
            else:
                await self.send_json({"type": "error", "message": payload})

        # 6) Draw offer / accept / decline
        elif msg_type == "draw_offer":
            ok, payload = await self.offer_draw()
            if ok:
                await self.channel_layer.group_send(self.room_name, {
                    "type": "broadcast",
                    "payload": {"type": "state", **payload}
                })
            else:
                await self.send_json({"type": "error", "message": payload})

        elif msg_type == "draw_accept":
            ok, payload = await self.accept_draw()
            if ok:
                await self.channel_layer.group_send(self.room_name, {
                    "type": "broadcast",
                    "payload": {"type": "state", **payload}
                })
            else:
                await self.send_json({"type": "error", "message": payload})

        elif msg_type == "draw_decline":
            ok, payload = await self.decline_draw()
            if ok:
                await self.channel_layer.group_send(self.room_name, {
                    "type": "broadcast",
                    "payload": {"type": "state", **payload}
                })
            else:
                await self.send_json({"type": "error", "message": payload})

        else:
            await self.send_json({"type": "error", "message": "Unknown message type"})

    async def broadcast(self, event):
        await self.send_json(event["payload"])

    async def send_json(self, obj):
        await self.send(text_data=json.dumps(obj))

    # ---------------- DB helpers ----------------
    @database_sync_to_async
    def get_game(self):
        return Game.objects.get(id=self.game_id)

    def build_state(self, g: Game, board: chess.Board, moves_list):
        return {
            "fen": board.fen(),
            "moves": moves_list,
            "turn": "white" if board.turn == chess.WHITE else "black",
            "status": g.status,
            "white": g.white.username if g.white else None,
            "black": g.black.username if g.black else None,
            "white_time": g.white_time,
            "black_time": g.black_time,
            "last_move_ts": g.last_move_ts.isoformat() if g.last_move_ts else None,
            "result": g.result,

            # ✅ IMPORTANT: expose draw state to frontend
            "draw_offered_by": g.draw_offered_by.username if g.draw_offered_by else None,
            "draw_offered_by_id": g.draw_offered_by_id,
        }

    @database_sync_to_async
    def get_state(self):
        g = Game.objects.get(id=self.game_id)
        board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)
        moves_list = [m for m in g.moves.split(" ") if m.strip()]
        return self.build_state(g, board, moves_list)

    @database_sync_to_async
    def get_legal_tos(self, frm):
        g = Game.objects.get(id=self.game_id)
        board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)

        if not frm or len(frm) != 2:
            return []

        try:
            from_sq = chess.parse_square(frm)
        except Exception:
            return []

        tos = []
        for mv in board.legal_moves:
            if mv.from_square == from_sq:
                tos.append(chess.square_name(mv.to_square))
        return tos

    @database_sync_to_async
    def apply_move(self, uci):
        g = Game.objects.get(id=self.game_id)

        board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)
        moves_list = [m for m in g.moves.split(" ") if m.strip()]

        # If finished, just return state
        if g.status == "FINISHED":
            return (True, self.build_state(g, board, moves_list))

        now = timezone.now()

        # ---- CHESS CLOCK: subtract time from side-to-move BEFORE making the move ----
        if g.last_move_ts:
            elapsed = int((now - g.last_move_ts).total_seconds())
            if elapsed < 0:
                elapsed = 0

            if board.turn == chess.WHITE:
                g.white_time = max(0, g.white_time - elapsed)
            else:
                g.black_time = max(0, g.black_time - elapsed)

        # If time ran out, finish immediately
        if g.white_time == 0:
            g.status = "FINISHED"
            g.result = "Black wins on time"
            g.draw_offered_by = None
            g.save()
            return (True, self.build_state(g, board, moves_list))

        if g.black_time == 0:
            g.status = "FINISHED"
            g.result = "White wins on time"
            g.draw_offered_by = None
            g.save()
            return (True, self.build_state(g, board, moves_list))

        # ---- Validate move ----
        if not uci:
            return (False, "Move missing.")

        try:
            move = chess.Move.from_uci(uci)
        except Exception:
            return (False, "Invalid move format.")

        if move not in board.legal_moves:
            return (False, "Illegal move.")

        # ---- Apply move ----
        board.push(move)

        g.fen = board.fen()
        moves_list.append(uci)
        g.moves = " ".join(moves_list)

        # ✅ Common rule: any move cancels a draw offer
        g.draw_offered_by = None

        # Turn started now (after move, the other player is to move)
        g.last_move_ts = now

        # ---- Result detection ----
        if board.is_checkmate():
            winner = "White" if board.turn == chess.BLACK else "Black"
            g.status = "FINISHED"
            g.result = f"{winner} wins by checkmate"

        elif board.is_stalemate():
            g.status = "FINISHED"
            g.result = "Draw by stalemate"

        elif board.is_insufficient_material():
            g.status = "FINISHED"
            g.result = "Draw by insufficient material"

        g.save()
        return (True, self.build_state(g, board, moves_list))

    # ---------------- RESIGN / DRAW ----------------
    @database_sync_to_async
    def resign_game(self):
        g = Game.objects.get(id=self.game_id)
        if g.status != "PLAYING":
            return (False, "Game is not playing.")

        user = self.scope["user"]
        if not (g.white_id == user.id or g.black_id == user.id):
            return (False, "Not a player.")

        winner = "Black" if g.white_id == user.id else "White"
        g.status = "FINISHED"
        g.result = f"{winner} wins by resignation"
        g.draw_offered_by = None
        g.save()

        board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)
        moves_list = [m for m in g.moves.split(" ") if m.strip()]
        return (True, self.build_state(g, board, moves_list))

    @database_sync_to_async
    def offer_draw(self):
        g = Game.objects.get(id=self.game_id)
        if g.status != "PLAYING":
            return (False, "Game is not playing.")

        user = self.scope["user"]
        if not (g.white_id == user.id or g.black_id == user.id):
            return (False, "Not a player.")

        g.draw_offered_by = user
        g.save()

        board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)
        moves_list = [m for m in g.moves.split(" ") if m.strip()]
        return (True, self.build_state(g, board, moves_list))

    @database_sync_to_async
    def accept_draw(self):
        g = Game.objects.get(id=self.game_id)
        if g.status != "PLAYING":
            return (False, "Game is not playing.")

        user = self.scope["user"]
        if not (g.white_id == user.id or g.black_id == user.id):
            return (False, "Not a player.")

        if not g.draw_offered_by_id:
            return (False, "No draw offer to accept.")

        if g.draw_offered_by_id == user.id:
            return (False, "You offered the draw. Opponent must accept.")

        g.status = "FINISHED"
        g.result = "Draw by agreement"
        g.draw_offered_by = None
        g.save()

        board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)
        moves_list = [m for m in g.moves.split(" ") if m.strip()]
        return (True, self.build_state(g, board, moves_list))

    @database_sync_to_async
    def decline_draw(self):
        g = Game.objects.get(id=self.game_id)
        if g.status != "PLAYING":
            return (False, "Game is not playing.")

        user = self.scope["user"]
        if not (g.white_id == user.id or g.black_id == user.id):
            return (False, "Not a player.")

        if not g.draw_offered_by_id:
            board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)
            moves_list = [m for m in g.moves.split(" ") if m.strip()]
            return (True, self.build_state(g, board, moves_list))

        if g.draw_offered_by_id == user.id:
            return (False, "Opponent must decline.")

        g.draw_offered_by = None
        g.save()

        board = chess.Board() if g.fen == "startpos" else chess.Board(g.fen)
        moves_list = [m for m in g.moves.split(" ") if m.strip()]
        return (True, self.build_state(g, board, moves_list))