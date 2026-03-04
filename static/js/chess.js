(() => {
  const GAME = window.__GAME__;
  const boardEl = document.getElementById("board");
  const moveListEl = document.getElementById("moveList");
  const statusLine = document.getElementById("statusLine");

  // Chat
  const chatBox = document.getElementById("chatBox");
  const chatForm = document.getElementById("chatForm");
  const chatInput = document.getElementById("chatInput");

  // Clocks
  const whiteClockEl = document.getElementById("whiteClock");
  const blackClockEl = document.getElementById("blackClock");

  // Resign / Draw UI (optional — only works if buttons exist in game.html)
  const btnResign = document.getElementById("btnResign");
  const btnOfferDraw = document.getElementById("btnOfferDraw");
  const btnAcceptDraw = document.getElementById("btnAcceptDraw");
  const btnDeclineDraw = document.getElementById("btnDeclineDraw");
  const drawStatus = document.getElementById("drawStatus");

  // ---------- WebSocket ----------
  function wsUrl() {
    return `${GAME.wsScheme}://${location.host}/ws/game/${GAME.id}/`;
  }
  const ws = new WebSocket(wsUrl());
  window.__WS__ = ws; // used by webrtc.js

  function wsSend(obj) {
    if (ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify(obj));
  }

  // ---------- Helpers ----------
  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    }[c]));
  }

  // ---------- Chat ----------
  function addChatLine(name, text) {
    if (!chatBox) return;
    const div = document.createElement("div");
    div.className = "chat-msg";
    div.innerHTML = `<span class="chat-name">${escapeHtml(name)}:</span> ${escapeHtml(text)}`;
    chatBox.appendChild(div);
    chatBox.scrollTop = chatBox.scrollHeight;
  }

  if (chatForm) {
    chatForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const text = (chatInput?.value || "").trim();
      if (!text) return;
      wsSend({ type: "chat", text });
      chatInput.value = "";
    });
  }

  // ---------- Clock ----------
  const clock = {
    white: 0,
    black: 0,
    turn: "white",
    lastTs: null,
    status: "WAITING",
  };

  function fmtTime(sec) {
    sec = Math.max(0, sec | 0);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function renderClocks() {
    if (whiteClockEl) whiteClockEl.textContent = fmtTime(clock.white);
    if (blackClockEl) blackClockEl.textContent = fmtTime(clock.black);
  }

  setInterval(() => {
    if (!clock.lastTs) return;
    if (clock.status !== "PLAYING") return;

    if (clock.turn === "white") clock.white = Math.max(0, clock.white - 1);
    else clock.black = Math.max(0, clock.black - 1);

    renderClocks();
  }, 1000);

  // ---------- Highlighting ----------
  function clearHighlights() {
    if (!boardEl) return;
    boardEl.querySelectorAll(".square.hl").forEach((el) => el.classList.remove("hl"));
  }

  function highlightSquares(tos) {
    clearHighlights();
    (tos || []).forEach((sqName) => {
      const el = boardEl.querySelector(`.square[data-square="${sqName}"]`);
      if (el) el.classList.add("hl");
    });
  }

  // ---------- Board Rendering ----------
  function fenToBoard(fen) {
    const rows = fen.split(" ")[0].split("/");
    const grid = [];
    for (const row of rows) {
      const line = [];
      for (const ch of row) {
        const n = parseInt(ch, 10);
        if (!Number.isNaN(n)) {
          for (let i = 0; i < n; i++) line.push(null);
        } else {
          line.push(ch);
        }
      }
      grid.push(line);
    }
    return grid; // 8x8 rank8..rank1
  }

  function pieceImage(pieceChar) {
    const isWhite = pieceChar === pieceChar.toUpperCase();
    const map = { p: "P", n: "N", b: "B", r: "R", q: "Q", k: "K" };
    const code = map[pieceChar.toLowerCase()];
    return `/static/pieces/${isWhite ? "w" : "b"}${code}.png`;
  }

  function toSquare(r, c) {
    const file = "abcdefgh"[c];
    const rank = (8 - r);
    return `${file}${rank}`;
  }

  function guessPromotionUci(from, to) {
    const toRank = parseInt(to[1], 10);
    if (toRank === 8 || toRank === 1) return `${from}${to}q`;
    return `${from}${to}`;
  }

  function renderBoard(fen) {
    if (!boardEl) return;
    const grid = fenToBoard(fen);
    boardEl.innerHTML = "";

    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const sq = document.createElement("div");
        sq.className = `square ${(r + c) % 2 === 0 ? "light" : "dark"}`;
        sq.dataset.square = toSquare(r, c);

        sq.addEventListener("dragover", (e) => e.preventDefault());
        sq.addEventListener("drop", (e) => {
          e.preventDefault();
          const from = e.dataTransfer.getData("text/plain");
          const to = sq.dataset.square;
          if (!from || !to || from === to) return;

          wsSend({ type: "move", uci: guessPromotionUci(from, to) });
        });

        const piece = grid[r][c];
        if (piece) {
          const p = document.createElement("div");
          p.className = "piece";
          p.draggable = true;
          p.dataset.from = sq.dataset.square;
          p.style.backgroundImage = `url(${pieceImage(piece)})`;

          p.addEventListener("dragstart", (e) => {
            e.dataTransfer.setData("text/plain", p.dataset.from);
          });

          // Click a piece -> ask server for legal moves
          p.addEventListener("click", () => {
            wsSend({ type: "legal_moves", from: p.dataset.from });
          });

          sq.appendChild(p);
        }

        boardEl.appendChild(sq);
      }
    }
  }

  function renderMoves(moves) {
    if (!moveListEl) return;
    moveListEl.innerHTML = "";
    (moves || []).forEach((uci) => {
      const li = document.createElement("li");
      li.textContent = uci;
      moveListEl.appendChild(li);
    });
  }

  // ---------- Resign + Draw UI ----------
  function myUsernameFromState(state) {
    // role is "white" or "black"
    if (GAME.role === "white") return state.white;
    if (GAME.role === "black") return state.black;
    return null;
  }

  function updateDrawUI(state) {
    if (!btnOfferDraw || !btnAcceptDraw || !btnDeclineDraw || !drawStatus) return;

    const offeredBy = state.draw_offered_by || null;
    const myName = myUsernameFromState(state);

    drawStatus.textContent = offeredBy ? `Draw offered by: ${offeredBy}` : "";

    if (state.status !== "PLAYING") {
      btnOfferDraw.disabled = true;
      btnAcceptDraw.disabled = true;
      btnDeclineDraw.disabled = true;
      btnAcceptDraw.style.display = "none";
      btnDeclineDraw.style.display = "none";
      return;
    }

    if (!offeredBy) {
      btnOfferDraw.disabled = false;
      btnOfferDraw.textContent = "Offer Draw";
      btnAcceptDraw.style.display = "none";
      btnDeclineDraw.style.display = "none";
      return;
    }

    // draw offered exists
    if (offeredBy === myName) {
      // I offered -> waiting
      btnOfferDraw.disabled = true;
      btnOfferDraw.textContent = "Draw Offered…";
      btnAcceptDraw.style.display = "none";
      btnDeclineDraw.style.display = "none";
    } else {
      // opponent offered -> accept/decline
      btnOfferDraw.disabled = true;
      btnOfferDraw.textContent = "Offer Draw";
      btnAcceptDraw.style.display = "";
      btnDeclineDraw.style.display = "";
      btnAcceptDraw.disabled = false;
      btnDeclineDraw.disabled = false;
    }
  }

  if (btnResign) {
    btnResign.addEventListener("click", () => {
      if (!confirm("Resign the game?")) return;
      wsSend({ type: "resign" });
    });
  }
  if (btnOfferDraw) btnOfferDraw.addEventListener("click", () => wsSend({ type: "draw_offer" }));
  if (btnAcceptDraw) btnAcceptDraw.addEventListener("click", () => wsSend({ type: "draw_accept" }));
  if (btnDeclineDraw) btnDeclineDraw.addEventListener("click", () => wsSend({ type: "draw_decline" }));

  // ---------- Game Over Popup ----------
  let shownResult = false;
  function maybeShowGameOver(state) {
    if (shownResult) return;
    if (state.status === "FINISHED" && state.result) {
      shownResult = true;
      setTimeout(() => alert(`Game Over\n\n${state.result}`), 100);
    }
  }

  // ---------- WebSocket events ----------
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);

    if (msg.type === "state") {
      renderBoard(msg.fen);
      renderMoves(msg.moves);
      clearHighlights();

      if (statusLine) statusLine.textContent = `Turn: ${msg.turn} | Status: ${msg.status}`;

      // clock sync
      clock.white = msg.white_time ?? clock.white;
      clock.black = msg.black_time ?? clock.black;
      clock.turn = msg.turn ?? clock.turn;
      clock.lastTs = msg.last_move_ts || clock.lastTs;
      clock.status = msg.status || clock.status;
      renderClocks();

      // resign/draw UI
      updateDrawUI(msg);

      // game result popup
      maybeShowGameOver(msg);

      // disable resign when finished
      if (msg.status === "FINISHED" && btnResign) btnResign.disabled = true;
    }

    if (msg.type === "legal_moves_result") {
      highlightSquares(msg.tos || []);
    }

    if (msg.type === "chat") {
      addChatLine(msg.name, msg.text);
    }

    if (msg.type === "error") {
      alert(msg.message);
    }
  };

  ws.onopen = () => console.log("WS connected");
  ws.onclose = () => console.log("WS closed");
})();