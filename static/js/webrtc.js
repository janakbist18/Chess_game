(() => {
  const GAME = window.__GAME__;
  const ws = window.__WS__;
  if (!ws) return;

  const localVideo = document.getElementById("localVideo");
  const remoteVideo = document.getElementById("remoteVideo");
  const btnMic = document.getElementById("btnMic");
  const btnCam = document.getElementById("btnCam");
  const btnHangup = document.getElementById("btnHangup");
  const callStatus = document.getElementById("callStatus");

  const iceServers = [{ urls: "stun:stun.l.google.com:19302" }];

  let pc = null;
  let localStream = null;
  let micEnabled = true;
  let camEnabled = true;

  function setStatus(s) { callStatus.textContent = `Call: ${s}`; }

  async function startLocalMedia() {
    if (localStream) return localStream;
    localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    localVideo.srcObject = localStream;
    return localStream;
  }

  function createPeer() {
    pc = new RTCPeerConnection({ iceServers });

    // Remote track handling
    pc.ontrack = (event) => {
      remoteVideo.srcObject = event.streams[0];
    };

    // ICE candidates
    pc.onicecandidate = (event) => {
      if (event.candidate) {
        ws.send(JSON.stringify({ type: "webrtc_ice", candidate: event.candidate }));
      }
    };

    return pc;
  }

  async function ensurePeerWithTracks() {
    if (!pc) createPeer();
    const stream = await startLocalMedia();

    // Add tracks once
    const senders = pc.getSenders();
    if (senders.length === 0) {
      stream.getTracks().forEach((t) => pc.addTrack(t, stream));
    }
  }

  async function makeOffer() {
    await ensurePeerWithTracks();
    setStatus("calling...");

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    ws.send(JSON.stringify({ type: "webrtc_offer", sdp: pc.localDescription }));
  }

  async function handleOffer(sdp) {
    await ensurePeerWithTracks();
    setStatus("incoming offer...");

    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    ws.send(JSON.stringify({ type: "webrtc_answer", sdp: pc.localDescription }));
    setStatus("connected");
  }

  async function handleAnswer(sdp) {
    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    setStatus("connected");
  }

  async function handleIce(candidate) {
    if (!pc) return;
    try { await pc.addIceCandidate(candidate); } catch (e) {}
  }

  function hangup(sendSignal = true) {
    if (sendSignal) {
      ws.send(JSON.stringify({ type: "webrtc_hangup" }));
    }
    setStatus("ended");

    if (pc) { pc.close(); pc = null; }
    if (remoteVideo.srcObject) remoteVideo.srcObject = null;
  }

  // Buttons
  btnMic.addEventListener("click", () => {
    if (!localStream) return;
    micEnabled = !micEnabled;
    localStream.getAudioTracks().forEach(t => t.enabled = micEnabled);
    btnMic.textContent = micEnabled ? "Mute Mic" : "Unmute Mic";
  });

  btnCam.addEventListener("click", () => {
    if (!localStream) return;
    camEnabled = !camEnabled;
    localStream.getVideoTracks().forEach(t => t.enabled = camEnabled);
    btnCam.textContent = camEnabled ? "Camera Off" : "Camera On";
  });

  btnHangup.addEventListener("click", () => hangup(true));

  // Receive signaling through WebSocket (chess.js also listens; that’s fine)
  ws.addEventListener("message", async (ev) => {
    const msg = JSON.parse(ev.data);

    if (msg.type === "webrtc_offer" && GAME.role === "black") {
      await handleOffer(msg.sdp);
    }
    if (msg.type === "webrtc_answer" && GAME.role === "white") {
      await handleAnswer(msg.sdp);
    }
    if (msg.type === "webrtc_ice") {
      await handleIce(msg.candidate);
    }
    if (msg.type === "webrtc_hangup") {
      hangup(false);
    }
  });

  // Auto-start call when WS is open:
  // White makes the offer after a short delay (lets both connect first)
  ws.addEventListener("open", async () => {
    setStatus("ready");
    try {
      await startLocalMedia();
      setStatus("media ready");
      if (GAME.role === "white") {
        setTimeout(() => makeOffer(), 900);
      } else {
        setStatus("waiting for offer");
      }
    } catch (e) {
      setStatus("media blocked (allow camera/mic)");
    }
  });
})();